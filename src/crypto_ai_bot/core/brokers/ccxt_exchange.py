# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .base import (
    ExchangeInterface,
    ExchangeError,
    TransientExchangeError,
    PermanentExchangeError,
)
from .symbols import normalize_symbol, normalize_timeframe, to_exchange_symbol
from crypto_ai_bot.utils.retry import retry
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils import metrics


# --- мягкая зависимость от ccxt ------------------------------------------------
try:
    import ccxt  # type: ignore
    _HAS_CCXT = True
except Exception as _e:
    ccxt = None  # type: ignore
    _HAS_CCXT = False
    _IMPORT_ERROR = _e


# --- вспомогательные вещи ------------------------------------------------------

def _to_float(x: Any) -> float:
    if isinstance(x, Decimal):
        return float(x)
    try:
        return float(x)
    except Exception:
        return 0.0


def _now_ms() -> int:
    return int(time.time() * 1000)


def _labels(method: str, exchange: str, code: Optional[int] = None) -> Dict[str, str]:
    lab = {"method": method, "exchange": (exchange or "").lower()}
    if code is not None:
        lab["code"] = str(code)
    return lab


# --- CcxtExchange --------------------------------------------------------------

class CcxtExchange(ExchangeInterface):
    """
    Реализация интерфейса биржи поверх CCXT.
    Все вызовы сети идут через retry + circuit breaker и пишут метрики.
    """

    def __init__(self, ccxt_client: Any, *, exchange_name: str, cfg: Any):
        self._x = ccxt_client
        self._name = exchange_name
        self._cfg = cfg

        # circuit breaker (значения можно вынести в Settings при желании)
        self._cb = CircuitBreaker()

        # настройки повторов/таймаутов из Settings
        self._retries = int(getattr(cfg, "HTTP_RETRIES", 2))
        self._backoff_base = float(getattr(cfg, "HTTP_BACKOFF_BASE_SEC", 0.2))
        self._jitter = float(getattr(cfg, "HTTP_BACKOFF_JITTER_SEC", 0.1))
        self._timeout_sec = float(getattr(cfg, "HTTP_TIMEOUT_SEC", 10.0))

    # ---- фабричный конструктор ------------------------------------------------

    @classmethod
    def from_settings(cls, cfg: Any) -> "CcxtExchange":
        if not _HAS_CCXT:
            raise PermanentExchangeError(
                f"ccxt is not installed: {_IMPORT_ERROR!r}. Please add 'ccxt' to requirements."
            )

        exchange_name = str(getattr(cfg, "EXCHANGE", "binance")).lower()
        if not hasattr(ccxt, exchange_name):
            raise PermanentExchangeError(f"Unknown exchange for ccxt: {exchange_name!r}")

        # инициализируем инстанс ccxt.<exchange>() без чтения ENV
        klass = getattr(ccxt, exchange_name)
        client = klass(
            {
                "enableRateLimit": True,
                "timeout": int(float(getattr(cfg, "HTTP_TIMEOUT_SEC", 10.0)) * 1000),
                # proxy, verbose и прочее можно прокинуть через cfg.EXTRA при желании
            }
        )

        # API-ключи (если заданы)
        api_key = getattr(cfg, "CCXT_API_KEY", None)
        api_secret = getattr(cfg, "CCXT_API_SECRET", None)
        password = getattr(cfg, "CCXT_PASSWORD", None)
        uid = getattr(cfg, "CCXT_UID", None)

        if api_key:
            client.apiKey = api_key
        if api_secret:
            client.secret = api_secret
        if password:
            client.password = password
        if uid:
            client.uid = uid

        return cls(client, exchange_name=exchange_name, cfg=cfg)

    # ---- публичный API (ExchangeInterface) -----------------------------------

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        """
        Возвращает список баров в формате CCXT:
          [[ts_ms, open, high, low, close, volume], ...] (по возрастанию времени)
        """
        sym = normalize_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        ex_sym = to_exchange_symbol(sym, self._name)

        @retry(
            retries=self._retries,
            backoff_base=self._backoff_base,
            jitter=self._jitter,
            retry_on=self._transient_errors_tuple(),
            on_retry=lambda i, e: metrics.inc(
                "broker_retry_total", _labels("fetch_ohlcv", self._name)
            ),
        )
        def _do():
            t0 = time.perf_counter()
            try:
                rows = self._cb.call(
                    lambda: self._x.fetch_ohlcv(ex_sym, timeframe=tf, limit=int(limit)),
                    key=f"{self._name}:ohlcv:{ex_sym}:{tf}",
                    timeout=self._timeout_sec,
                    fail_threshold=5,
                    open_seconds=10.0,
                )
                metrics.inc("broker_requests_total", _labels("fetch_ohlcv", self._name, 200))
                return rows
            except Exception as e:
                metrics.inc("broker_requests_total", _labels("fetch_ohlcv", self._name, 599))
                raise e
            finally:
                dur = time.perf_counter() - t0
                metrics.observe("broker_latency_seconds", dur, _labels("fetch_ohlcv", self._name))

        rows = _do()  # type: ignore[assignment]
        # CCXT возвращает уже по возрастанию, но перестрахуемся:
        rows.sort(key=lambda r: r[0])
        # приводим числа к float
        out: List[List[float]] = []
        for r in rows:
            ts = float(r[0])
            o, h, l, c, v = map(_to_float, r[1:6])
            out.append([ts, o, h, l, c, v])
        return out

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        ex_sym = to_exchange_symbol(sym, self._name)

        @retry(
            retries=self._retries,
            backoff_base=self._backoff_base,
            jitter=self._jitter,
            retry_on=self._transient_errors_tuple(),
            on_retry=lambda i, e: metrics.inc(
                "broker_retry_total", _labels("fetch_ticker", self._name)
            ),
        )
        def _do():
            t0 = time.perf_counter()
            try:
                data = self._cb.call(
                    lambda: self._x.fetch_ticker(ex_sym),
                    key=f"{self._name}:ticker:{ex_sym}",
                    timeout=self._timeout_sec,
                    fail_threshold=5,
                    open_seconds=10.0,
                )
                metrics.inc("broker_requests_total", _labels("fetch_ticker", self._name, 200))
                return data
            except Exception as e:
                metrics.inc("broker_requests_total", _labels("fetch_ticker", self._name, 599))
                raise e
            finally:
                dur = time.perf_counter() - t0
                metrics.observe("broker_latency_seconds", dur, _labels("fetch_ticker", self._name))

        data = _do()
        # нормализуем минимальный контракт: last/close/bid/ask
        last = data.get("last") or data.get("close")
        return {
            "symbol": sym,
            "exchange_symbol": ex_sym,
            "last": _to_float(last),
            "close": _to_float(data.get("close")),
            "bid": _to_float(data.get("bid")),
            "ask": _to_float(data.get("ask")),
            "timestamp": int(data.get("timestamp") or data.get("datetime") or _now_ms()),
            "raw": data,
        }

    def create_order(
        self,
        symbol: str,
        type_: str,
        side: str,
        amount: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        ex_sym = to_exchange_symbol(sym, self._name)
        typ = str(type_).lower()
        sd = str(side).lower()

        if typ not in {"market", "limit"}:
            raise PermanentExchangeError(f"Unsupported order type: {type_!r}")
        if sd not in {"buy", "sell"}:
            raise PermanentExchangeError(f"Unsupported side: {side!r}")

        params: Dict[str, Any] = {}
        if client_order_id:
            # большинство бирж CCXT уважают clientOrderId в params
            params["clientOrderId"] = client_order_id

        amt = _to_float(amount)
        prc = None if price is None else _to_float(price)

        @retry(
            retries=self._retries,
            backoff_base=self._backoff_base,
            jitter=self._jitter,
            retry_on=self._transient_errors_tuple(),
            on_retry=lambda i, e: metrics.inc(
                "broker_retry_total", _labels("create_order", self._name)
            ),
        )
        def _do():
            t0 = time.perf_counter()
            try:
                order = self._cb.call(
                    lambda: self._x.create_order(ex_sym, typ, sd, amt, prc, params),
                    key=f"{self._name}:order:{ex_sym}:{sd}:{typ}",
                    timeout=self._timeout_sec,
                    fail_threshold=5,
                    open_seconds=10.0,
                )
                metrics.inc("broker_requests_total", _labels("create_order", self._name, 200))
                return order
            except Exception as e:
                metrics.inc("broker_requests_total", _labels("create_order", self._name, 599))
                raise e
            finally:
                dur = time.perf_counter() - t0
                metrics.observe("broker_latency_seconds", dur, _labels("create_order", self._name))

        return _do()

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not order_id:
            raise PermanentExchangeError("order_id is required")

        @retry(
            retries=self._retries,
            backoff_base=self._backoff_base,
            jitter=self._jitter,
            retry_on=self._transient_errors_tuple(),
            on_retry=lambda i, e: metrics.inc(
                "broker_retry_total", _labels("cancel_order", self._name)
            ),
        )
        def _do():
            t0 = time.perf_counter()
            try:
                res = self._cb.call(
                    lambda: self._x.cancel_order(order_id),
                    key=f"{self._name}:cancel:{order_id}",
                    timeout=self._timeout_sec,
                    fail_threshold=5,
                    open_seconds=10.0,
                )
                metrics.inc("broker_requests_total", _labels("cancel_order", self._name, 200))
                return res
            except Exception as e:
                metrics.inc("broker_requests_total", _labels("cancel_order", self._name, 599))
                raise e
            finally:
                dur = time.perf_counter() - t0
                metrics.observe("broker_latency_seconds", dur, _labels("cancel_order", self._name))

        return _do()

    def fetch_balance(self) -> Dict[str, Any]:
        @retry(
            retries=self._retries,
            backoff_base=self._backoff_base,
            jitter=self._jitter,
            retry_on=self._transient_errors_tuple(),
            on_retry=lambda i, e: metrics.inc(
                "broker_retry_total", _labels("fetch_balance", self._name)
            ),
        )
        def _do():
            t0 = time.perf_counter()
            try:
                res = self._cb.call(
                    lambda: self._x.fetch_balance(),
                    key=f"{self._name}:balance",
                    timeout=self._timeout_sec,
                    fail_threshold=5,
                    open_seconds=10.0,
                )
                metrics.inc("broker_requests_total", _labels("fetch_balance", self._name, 200))
                return res
            except Exception as e:
                metrics.inc("broker_requests_total", _labels("fetch_balance", self._name, 599))
                raise e
            finally:
                dur = time.perf_counter() - t0
                metrics.observe("broker_latency_seconds", dur, _labels("fetch_balance", self._name))

        return _do()

    # ---- необязательное закрытие ресурсов ------------------------------------

    def close(self) -> None:
        try:
            if hasattr(self._x, "close"):
                self._x.close()
        except Exception:
            pass

    # ---- классификация ошибок для retry --------------------------------------

    @staticmethod
    def _transient_errors_tuple():
        """
        Набор исключений, при которых имеет смысл ретраить вызовы.
        Если ccxt недоступен (теоретически), используем общий Exception — но это маловероятно.
        """
        if not _HAS_CCXT:
            return (Exception,)  # fallback

        transient = (
            ccxt.RequestTimeout,
            ccxt.NetworkError,
            ccxt.DDoSProtection,
            ccxt.ExchangeNotAvailable,
            ccxt.RateLimitExceeded,
            ccxt.OnMaintenance,
        )
        # также считаем наш TransientExchangeError ретраибл
        return transient + (TransientExchangeError,)
