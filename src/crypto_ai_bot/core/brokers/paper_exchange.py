# src/crypto_ai_bot/core/brokers/paper_exchange.py
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    ExchangeInterface,
    ExchangeError,
    TransientExchangeError,
    PermanentExchangeError,
)
from .symbols import normalize_symbol, normalize_timeframe, to_exchange_symbol, split_symbol
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.retry import retry
from crypto_ai_bot.utils import metrics

# --- мягкая зависимость от ccxt: для рыночных данных (тикер/ohlcv) ------------
try:
    import ccxt  # type: ignore
    _HAS_CCXT = True
except Exception as _e:
    ccxt = None  # type: ignore
    _HAS_CCXT = False
    _IMPORT_ERROR = _e


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_float(x: Any, default: float = 0.0) -> float:
    if isinstance(x, Decimal):
        try:
            return float(x)
        except Exception:
            return default
    try:
        return float(x)
    except Exception:
        return default


def _labels(method: str, exchange: str, code: Optional[int] = None) -> Dict[str, str]:
    lab = {"method": method, "exchange": (exchange or "paper").lower()}
    if code is not None:
        lab["code"] = str(code)
    return lab


class PaperExchange(ExchangeInterface):
    """
    Бумажная биржа (paper):
    - Балансы/исполнение — целиком в памяти процесса.
    - Рыночные данные — через ccxt (если установлен) анонимно (enableRateLimit=True).
      Если ccxt недоступен → бросаем PermanentExchangeError (для paper нужна цена).
    """

    @classmethod
    def from_settings(cls, cfg):
        return cls(cfg=cfg)

    def __init__(self, *, cfg: Any):
        self._cfg = cfg
        self._name = "paper"
        self._cb = CircuitBreaker()

        # тайминги/ретраи
        self._timeout_sec = float(getattr(cfg, "HTTP_TIMEOUT_SEC", 10.0))
        self._retries = int(getattr(cfg, "HTTP_RETRIES", 2))
        self._backoff_base = float(getattr(cfg, "HTTP_BACKOFF_BASE_SEC", 0.2))
        self._jitter = float(getattr(cfg, "HTTP_BACKOFF_JITTER_SEC", 0.1))

        # торговые параметры
        self._fee_pct = Decimal(getattr(cfg, "PAPER_FEE_PCT", Decimal("0.001")))
        self._slip_pct = Decimal(getattr(cfg, "PAPER_SLIPPAGE_PCT", Decimal("0.0005")))
        self._latency_ms = int(getattr(cfg, "PAPER_LATENCY_MS", 50))

        # стартовый баланс: используем BACKTEST_INITIAL_BALANCE как источник истины
        initial_quote = Decimal(getattr(cfg, "BACKTEST_INITIAL_BALANCE", Decimal("10000")))

        self._balances: Dict[str, Dict[str, float]] = {}  # {'USDT': {'free':..., 'used':..., 'total':...}, 'BTC': {...}}
        self._client = None  # ccxt client (lazy)

        # локальная защита от дублей client_order_id (на всякий случай)
        self._seen_client_oids: set[str] = set()

        # при первом запросе с символом инициализируем валюты
        self._init_done_for: set[str] = set()  # символы, для которых инициализировали баланс

        # сохраняем последнюю котировку для fallback
        self._last_ticker: Dict[str, Dict[str, Any]] = {}

        metrics.inc("broker_created_total", {"mode": "paper"})

    # ────────────────────────── вспомогательные вещи ───────────────────────────

    def _ensure_symbol_wallets(self, symbol: str) -> Tuple[str, str]:
        """Ленивая инициализация кошельков базовой/котируемой валют по символу."""
        base, quote = split_symbol(symbol)  # 'BTC/USDT' -> ('BTC', 'USDT')
        if symbol in self._init_done_for:
            return base, quote

        # если неизвестны валюты — создаём кошельки с нулём
        for cur in (base, quote):
            if cur not in self._balances:
                self._balances[cur] = {"free": 0.0, "used": 0.0, "total": 0.0}

        # пополняем КОТИРУЕМУЮ валюту стартовым балансом (если ещё пусто)
        if self._balances[quote]["total"] == 0.0:
            q0 = _to_float(getattr(self._cfg, "BACKTEST_INITIAL_BALANCE", 10000))
            self._balances[quote]["free"] = q0
            self._balances[quote]["total"] = q0

        self._init_done_for.add(symbol)
        return base, quote

    def _get_ccxt(self):
        if self._client is not None:
            return self._client
        if not _HAS_CCXT:
            raise PermanentExchangeError(
                f"ccxt is not installed: {_IMPORT_ERROR!r}. Install 'ccxt' to run paper-mode with market data."
            )
        ex_name = str(getattr(self._cfg, "EXCHANGE", "binance")).lower()
        if not hasattr(ccxt, ex_name):
            raise PermanentExchangeError(f"Unknown exchange for ccxt: {ex_name!r}")
        klass = getattr(ccxt, ex_name)
        self._client = klass({"enableRateLimit": True, "timeout": int(self._timeout_sec * 1000)})
        return self._client

    def _maybe_sleep_latency(self):
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000.0)

    # ───────────────────────────── публичный API ───────────────────────────────

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        sym = normalize_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        ex_sym = to_exchange_symbol(sym, str(getattr(self._cfg, "EXCHANGE", "binance")).lower())

        # нужен ccxt для данных
        x = self._get_ccxt()

        @retry(
            retries=self._retries,
            backoff_base=self._backoff_base,
            jitter=self._jitter,
            retry_on=(Exception,),
            on_retry=lambda i, e: metrics.inc("broker_retry_total", _labels("fetch_ohlcv", self._name)),
        )
        def _do():
            t0 = time.perf_counter()
            try:
                rows = self._cb.call(
                    lambda: x.fetch_ohlcv(ex_sym, timeframe=tf, limit=int(limit)),
                    key=f"paper:ohlcv:{ex_sym}:{tf}",
                    timeout=self._timeout_sec,
                    fail_threshold=5,
                    open_seconds=5.0,
                )
                metrics.inc("broker_requests_total", _labels("fetch_ohlcv", self._name, 200))
                return rows
            except Exception as e:
                metrics.inc("broker_requests_total", _labels("fetch_ohlcv", self._name, 599))
                raise e
            finally:
                metrics.observe("broker_latency_seconds", time.perf_counter() - t0, _labels("fetch_ohlcv", self._name))

        rows = _do()
        rows.sort(key=lambda r: r[0])
        out: List[List[float]] = []
        for r in rows:
            ts = _to_float(r[0])
            o, h, l, c, v = map(_to_float, r[1:6])
            out.append([ts, o, h, l, c, v])
        return out

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        ex_sym = to_exchange_symbol(sym, str(getattr(self._cfg, "EXCHANGE", "binance")).lower())
        x = self._get_ccxt()

        @retry(
            retries=self._retries,
            backoff_base=self._backoff_base,
            jitter=self._jitter,
            retry_on=(Exception,),
            on_retry=lambda i, e: metrics.inc("broker_retry_total", _labels("fetch_ticker", self._name)),
        )
        def _do():
            t0 = time.perf_counter()
            try:
                data = self._cb.call(
                    lambda: x.fetch_ticker(ex_sym),
                    key=f"paper:ticker:{ex_sym}",
                    timeout=self._timeout_sec,
                    fail_threshold=5,
                    open_seconds=5.0,
                )
                metrics.inc("broker_requests_total", _labels("fetch_ticker", self._name, 200))
                return data
            except Exception as e:
                metrics.inc("broker_requests_total", _labels("fetch_ticker", self._name, 599))
                raise e
            finally:
                metrics.observe("broker_latency_seconds", time.perf_counter() - t0, _labels("fetch_ticker", self._name))

        data = _do()
        last = _to_float(data.get("last") or data.get("close") or 0.0)
        bid = _to_float(data.get("bid") or last)
        ask = _to_float(data.get("ask") or last)
        ts = int(data.get("timestamp") or _now_ms())

        out = {
            "symbol": sym,
            "exchange_symbol": ex_sym,
            "last": last,
            "close": _to_float(data.get("close") or last),
            "bid": bid,
            "ask": ask,
            "timestamp": ts,
            "raw": data,
        }
        self._last_ticker[sym] = out
        return out

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
        typ = str(type_).lower()
        sd = str(side).lower()
        if typ not in {"market", "limit"}:
            raise PermanentExchangeError(f"Unsupported order type: {type_!r}")
        if sd not in {"buy", "sell"}:
            raise PermanentExchangeError(f"Unsupported side: {side!r}")

        # локальная идемпотентность (дополнительно к use-case)
        if client_order_id and client_order_id in self._seen_client_oids:
            return {
                "id": f"dup-{client_order_id}",
                "clientOrderId": client_order_id,
                "symbol": sym,
                "status": "duplicate",
                "filled": 0.0,
                "price": _to_float(price) if price is not None else None,
                "timestamp": _now_ms(),
            }
        if client_order_id:
            self._seen_client_oids.add(client_order_id)

        base, quote = self._ensure_symbol_wallets(sym)

        # получаем лучшую котировку
        try:
            tkr = self.fetch_ticker(sym)
        except Exception:
            # если не получилось — попробуем последний кэш
            tkr = self._last_ticker.get(sym)
            if not tkr:
                raise TransientExchangeError("no market data available for paper execution")

        bid = _to_float(tkr.get("bid") or tkr.get("last") or 0.0)
        ask = _to_float(tkr.get("ask") or tkr.get("last") or 0.0)
        last = _to_float(tkr.get("last") or 0.0)

        amt = _to_float(amount)
        if amt <= 0.0:
            raise PermanentExchangeError("amount must be > 0")

        # симулируем цену исполнения
        exec_price: float
        if typ == "market":
            if sd == "buy":
                exec_price = (ask or last) * (1.0 + float(self._slip_pct))
            else:
                exec_price = (bid or last) * (1.0 - float(self._slip_pct))
        else:  # limit
            limit_price = _to_float(price, default=0.0)
            # если лимит «пересекает» рынок — исполняем по лимитной
            if sd == "buy":
                if limit_price >= (ask or last):
                    exec_price = limit_price
                else:
                    exec_price = limit_price
            else:
                if limit_price <= (bid or last):
                    exec_price = limit_price
                else:
                    exec_price = limit_price

        # комиссия
        fee = exec_price * amt * _to_float(self._fee_pct, 0.0)

        # проверяем и обновляем балансы
        if sd == "buy":
            cost = exec_price * amt + fee
            if self._balances[quote]["free"] + 1e-12 < cost:
                raise PermanentExchangeError("insufficient funds (quote)")
            self._balances[quote]["free"] -= cost
            self._balances[quote]["total"] -= cost
            self._balances[base]["free"] += amt
            self._balances[base]["total"] += amt
        else:  # sell
            if self._balances[base]["free"] + 1e-12 < amt:
                raise PermanentExchangeError("insufficient funds (base)")
            proceeds = exec_price * amt - fee
            self._balances[base]["free"] -= amt
            self._balances[base]["total"] -= amt
            self._balances[quote]["free"] += proceeds
            self._balances[quote]["total"] += proceeds

        # имитируем сетевую задержку
        self._maybe_sleep_latency()

        order_id = f"paper-{int(time.time()*1000)}"
        res = {
            "id": order_id,
            "clientOrderId": client_order_id,
            "symbol": sym,
            "type": typ,
            "side": sd,
            "status": "closed",
            "filled": amt,
            "price": exec_price,
            "cost": exec_price * amt,
            "fee": {"currency": quote, "cost": fee, "rate": _to_float(self._fee_pct)},
            "timestamp": _now_ms(),
        }
        metrics.inc("broker_requests_total", _labels("create_order", self._name, 200))
        return res

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        metrics.inc("broker_requests_total", _labels("cancel_order", self._name, 200))
        return {"id": order_id, "status": "canceled", "timestamp": _now_ms()}

    def fetch_balance(self) -> Dict[str, Any]:
        free = {k: round(v["free"], 12) for k, v in self._balances.items()}
        total = {k: round(v["total"], 12) for k, v in self._balances.items()}
        used = {k: round(total[k] - free[k], 12) for k in total.keys()}
        metrics.inc("broker_requests_total", _labels("fetch_balance", self._name, 200))
        return {"free": free, "used": used, "total": total}

    def close(self) -> None:
        try:
            if self._client and hasattr(self._client, "close"):
                self._client.close()
        except Exception:
            pass
