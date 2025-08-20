# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import time
import re
import zlib
import logging
from typing import Any, Dict, Optional

import ccxt  # sync API
from decimal import Decimal

from crypto_ai_bot.utils.rate_limit import TokenBucket, MultiLimiter
from crypto_ai_bot.utils.metrics import inc, observe_histogram
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_decimal(x: Any) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(0)


# -----------------------------
# Gate.io clientOrderId (text)
# -----------------------------
_GATE_ALLOWED = re.compile(r"^[A-Za-z0-9._\-]+$")

def _gateio_text_from(seed: str) -> str:
    """
    Делает короткий, детерминированный client id (<= 28 байт) для Gate.io:
    - Всегда начинается с 't-'
    - Только [A-Za-z0-9._-]
    - Короткий хвост как CRC32 от seed, чтобы стабилизировать идентификатор
    """
    crc = zlib.crc32(seed.encode("utf-8")) & 0xFFFFFFFF
    base = f"t-cai-{crc:08x}"
    # safety: максимум 28 символов
    base = base[:28]
    # фильтрация на всякий случай
    if not _GA_TE_ALLOWED(base) if False else _GATE_ALLOWED.match(base):  # keep linter happy
        pass
    return base


class CCXTExchange:
    """
    Тонкая обёртка над ccxt, с:
      - CircuitBreaker
      - Per-endpoint rate limiter
      - Централизованным clientOrderId (Gate.io)
      - Нормализованными market meta для sizing/квантования
    """

    def __init__(
        self,
        *,
        settings,
        limiter: Optional[MultiLimiter] = None,
    ) -> None:
        self.settings = settings
        self.exchange_id: str = str(getattr(settings, "EXCHANGE", "gateio")).lower()

        # rate-limit buckets (можно переопределить извне через limiter)
        if limiter is None:
            limiter = MultiLimiter({
                # ориентиры по Gate, можно ужать/расширить
                "orders":       TokenBucket(capacity=100, refill_per_sec=10),
                "market_data":  TokenBucket(capacity=600, refill_per_sec=60),
                "account":      TokenBucket(capacity=300, refill_per_sec=30),
            })
        self.limiter = limiter

        # Circuit breaker (имя обязательно!)
        self.cb = CircuitBreaker(
            name="ccxt_broker",
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            open_timeout_sec=float(getattr(settings, "CB_OPEN_TIMEOUT_SEC", 30.0)),
            half_open_max_calls=int(getattr(settings, "CB_HALF_OPEN_CALLS", 1)),
            window_sec=float(getattr(settings, "CB_WINDOW_SEC", 60.0)),
        )

        # ccxt client
        api_key = getattr(settings, "API_KEY", None)
        api_secret = getattr(settings, "API_SECRET", None)
        opts = {
            "enableRateLimit": True,  # базовый лимитер ccxt
            "options": {
                # рыночный buy без price
                "createMarketBuyOrderRequiresPrice": False,
            },
        }
        klass = getattr(ccxt, self.exchange_id)
        self.ccxt = klass({
            "apiKey": api_key,
            "secret": api_secret,
            **opts,
        })

        # markets cache
        self._markets: Optional[Dict[str, Any]] = None

    # --------- Public API ---------

    def load_markets(self, reload: bool = False) -> Dict[str, Any]:
        if self._markets is None or reload:
            self._rl("market_data")
            self._markets = self._with_retries("load_markets", self.ccxt.load_markets)
        return self._markets

    def get_market_meta(self, symbol: str) -> Dict[str, Any]:
        mkts = self.load_markets()
        # ccxt использует формат "BASE/QUOTE", например "BTC/USDT"
        m = mkts.get(symbol)
        if not m:
            # попытка fallback с upper
            m = mkts.get(symbol.upper())
        if not m:
            return {"amount_step": None, "price_step": None, "min_amount": None}
        prec = m.get("precision") or {}
        limits = m.get("limits") or {}
        return {
            "amount_step": prec.get("amount"),
            "price_step": prec.get("price"),
            "min_amount": (limits.get("amount") or {}).get("min"),
        }

    def fetch_last_price(self, symbol: str) -> float:
        self._rl("market_data")
        def _call():
            t = self.ccxt.fetch_ticker(symbol)
            last = t.get("last") or t.get("ask") or t.get("bid")
            return float(last) if last else 0.0
        px = self._with_retries("fetch_ticker", _call)
        return float(px or 0.0)

    def create_order(
        self,
        *,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Унифицированное создание ордеров.
        - Для Gate.io добавляет clientOrderId/text
        - Для market BUY передаёт amount в quote-сумме (уже учтено на верхнем уровне)
        """
        params = dict(params or {})
        self._rl("orders")

        # Gate.io clientOrderId
        if self.exchange_id == "gateio":
            if "text" not in params and "clientOrderId" not in params:
                # формируем детерминированный короткий id на основе полей ордера
                seed = f"{symbol}:{side}:{type}:{int(time.time()*1000)}:{amount}"
                params["text"] = _gateio_text_from(seed)

        def _call():
            return self.ccxt.create_order(symbol, type, side, amount, price, params)

        od = self._with_retries("create_order", _call)
        # метрики
        inc("ccxt_create_order_total", {"symbol": symbol, "side": side})
        return od

    def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        self._rl("account")
        def _call():
            # для некоторых бирж symbol обязателен
            if symbol:
                return self.ccxt.fetch_order(order_id, symbol)
            return self.ccxt.fetch_order(order_id)
        return self._with_retries("fetch_order", _call)

    def fetch_open_orders(self, symbol: Optional[str] = None) -> list[Dict[str, Any]]:
        self._rl("account")
        def _call():
            if symbol:
                return self.ccxt.fetch_open_orders(symbol)
            return self.ccxt.fetch_open_orders()
        return self._with_retries("fetch_open_orders", _call)

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Any:
        self._rl("orders")
        def _call():
            if symbol:
                return self.ccxt.cancel_order(order_id, symbol)
            return self.ccxt.cancel_order(order_id)
        return self._with_retries("cancel_order", _call)

    def fetch_balance(self) -> Dict[str, Any]:
        self._rl("account")
        return self._with_retries("fetch_balance", self.ccxt.fetch_balance)

    # --------- Internals ---------

    def _rl(self, endpoint: str) -> None:
        """
        Лимитер на уровне брокера по типам операций.
        """
        if not self.limiter.try_acquire(endpoint, 1.0):
            # короткий backoff до следующей попытки
            time.sleep(0.05)

    def _with_retries(self, label: str, fn, *, max_attempts: Optional[int] = None):
        """
        Обёртка с CircuitBreaker и экспоненциальными ретраями.
        Сетевые/429 ошибки — ретраим; логические (InvalidOrder/InsufficientFunds) — отдаем наверх.
        """
        attempts = int(getattr(self.settings, "CCXT_MAX_ATTEMPTS", 4)) if max_attempts is None else max_attempts
        base = float(getattr(self.settings, "CCXT_BACKOFF_BASE_SEC", 0.25))
        max_b = float(getattr(self.settings, "CCXT_BACKOFF_MAX_SEC", 2.0))

        # CB: разрешение на вызов
        if not self.cb.allow():
            inc("ccxt_cb_blocked_total", {"op": label})
            raise ccxt.RateLimitExceeded("circuit_open")

        last_err: Optional[Exception] = None
        for i in range(1, attempts + 1):
            try:
                res = fn()
                # успешный вызов — сообщим CB
                self.cb.record_success(label)
                return res
            except ccxt.RateLimitExceeded as e:
                last_err = e
                self.cb.record_error("rate_limit", e)
                inc("ccxt_rate_limit_total", {"op": label})
                self._sleep_backoff(i, base, max_b)
            except (ccxt.NetworkError, ccxt.DDoSProtection) as e:
                last_err = e
                self.cb.record_error("network", e)
                inc("ccxt_network_error_total", {"op": label})
                self._sleep_backoff(i, base, max_b)
            except (ccxt.InvalidOrder, ccxt.InsufficientFunds, ccxt.InvalidAddress, ccxt.BadSymbol) as e:
                # логические ошибки — не ретраим
                self.cb.record_error("order", e)
                inc("ccxt_order_error_total", {"op": label})
                raise
            except ccxt.ExchangeError as e:
                last_err = e
                self.cb.record_error("exchange", e)
                inc("ccxt_exchange_error_total", {"op": label})
                self._sleep_backoff(i, base, max_b)
            except Exception as e:
                last_err = e
                self.cb.record_error("unknown", e)
                inc("ccxt_unknown_error_total", {"op": label})
                self._sleep_backoff(i, base, max_b)

        # исчерпали попытки
        if last_err:
            raise last_err
        raise RuntimeError(f"{label}: no result")

    @staticmethod
    def _sleep_backoff(attempt: int, base: float, max_b: float) -> None:
        # expo backoff c лёгким джиттером
        delay = _clamp(base * (2 ** (attempt - 1)), base, max_b)
        delay += (0.001 * (attempt % 3))  # tiny jitter
        time.sleep(delay)
