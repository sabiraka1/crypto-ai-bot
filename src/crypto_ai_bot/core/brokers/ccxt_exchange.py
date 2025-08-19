# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import logging
import time
import math
import hashlib
from typing import Any, Dict, List, Optional

from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger("brokers.ccxt_exchange")

try:
    import ccxt
    from ccxt.base.errors import (  # type: ignore
        DDoSProtection, RateLimitExceeded, ExchangeNotAvailable, NetworkError,
        RequestTimeout, AuthenticationError, PermissionDenied,
        InvalidOrder, InsufficientFunds, OrderNotFound
    )
except Exception:  # pragma: no cover
    ccxt = None
    class DDoSProtection(Exception): ...
    class RateLimitExceeded(Exception): ...
    class ExchangeNotAvailable(Exception): ...
    class NetworkError(Exception): ...
    class RequestTimeout(Exception): ...
    class AuthenticationError(Exception): ...
    class PermissionDenied(Exception): ...
    class InvalidOrder(Exception): ...
    class InsufficientFunds(Exception): ...
    class OrderNotFound(Exception): ...


# ---------------------- маленький per-endpoint limiter -----------------------

class _TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = max(1, capacity)
        self.tokens = float(self.capacity)
        self.refill_per_sec = max(0.0001, refill_per_sec)
        self._last = time.monotonic()

    def try_acquire(self, n: float = 1.0) -> bool:
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        # refill
        self.tokens = min(self.capacity, self.tokens + dt * self.refill_per_sec)
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


class _EndpointLimiter:
    """
    Простой limiter по типам эндпоинтов:
      - 'orders'
      - 'market_data'
      - 'account'
    Настраивается через Settings:
      RL_WINDOW_SEC (по умолчанию 10)
      RL_ORDERS_PER_10S, RL_MARKET_DATA_PER_10S, RL_ACCOUNT_PER_10S
    """
    def __init__(self, *, window_sec: int, orders: int, market_data: int, account: int) -> None:
        # переводим квоты в refill (tokens/sec)
        def mk(cap: int) -> _TokenBucket:
            refill = cap / float(max(1, window_sec))
            return _TokenBucket(capacity=cap, refill_per_sec=refill)

        self._buckets: Dict[str, _TokenBucket] = {
            "orders": mk(orders),
            "market_data": mk(market_data),
            "account": mk(account),
        }

    @classmethod
    def from_settings(cls, s: Any) -> "_EndpointLimiter":
        wnd = int(getattr(s, "RL_WINDOW_SEC", 10))
        return cls(
            window_sec=wnd,
            orders=int(getattr(s, "RL_ORDERS_PER_10S", 100)),       # по умолчанию «мягко»
            market_data=int(getattr(s, "RL_MARKET_DATA_PER_10S", 600)),
            account=int(getattr(s, "RL_ACCOUNT_PER_10S", 300)),
        )

    def acquire_or_raise(self, endpoint: str) -> None:
        b = self._buckets.get(endpoint)
        if b is None:
            # незнакомый endpoint — используем корзину orders
            b = self._buckets["orders"]
        if not b.try_acquire(1.0):
            raise RateLimitExceeded(f"local rate limit exceeded for '{endpoint}'")


# ------------------------------ CCXT обёртка ---------------------------------

def _kind_from_exc(e: Exception) -> str:
    if isinstance(e, (RateLimitExceeded, DDoSProtection)): return "rate_limit"
    if isinstance(e, (NetworkError, ExchangeNotAvailable, RequestTimeout)): return "network"
    if isinstance(e, (AuthenticationError, PermissionDenied)): return "auth"
    if isinstance(e, (InvalidOrder, InsufficientFunds, OrderNotFound)): return "order"
    return "unknown"


class CCXTExchange:
    """
    Минимально-дефолтная реализация интерфейса брокера.
    Важные моменты:
      • clientOrderId для Gate.io генерится здесь (параметр `text`), единая точка правды
      • per-endpoint rate-limiting (orders/market_data/account)
      • circuit-breaker для сетевых/лимитных ошибок
    """

    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")

        name = (exchange_name or getattr(settings, "EXCHANGE", "binance")).lower()
        if not hasattr(ccxt, name):
            raise ValueError(f"Unknown ccxt exchange: {name}")

        klass = getattr(ccxt, name)
        # enableRateLimit оставляем включённым — это «второй рубеж» защиты
        self.ccxt = klass({
            "apiKey": getattr(settings, "API_KEY", None),
            "secret": getattr(settings, "API_SECRET", None),
            "enableRateLimit": True,
            "options": {
                # для market BUY на Gate.io нам не нужен price
                "createMarketBuyOrderRequiresPrice": False,
            },
        })
        self.exchange_id = name
        self.settings = settings
        self.bus = bus

        # circuit-breaker параметры
        self.cb = CircuitBreaker(
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            recovery_time_sec=float(getattr(settings, "CB_RECOVERY_SEC", 10.0)),
            half_open_max_calls=int(getattr(settings, "CB_HALF_OPEN_MAX", 2)),
        )

        # per-endpoint limiter
        self._limiter = _EndpointLimiter.from_settings(settings)

    # -------------------------- utility: client id ---------------------------

    def _gateio_text_from(self, *, symbol: str, side: str, idem_hint: Optional[str]) -> str:
        """
        Формирует допустимый для Gate.io `text` (clientOrderId):
          - начинается с 't-'
          - длина <= 28
          - [A-Za-z0-9._-] (мы используем base36-хэш)
        Если есть idem_hint (например, idempotency_key из use-case), делаем стабильную строку.
        Иначе — уникальная строка с time-bucket, чтобы ретраи в том же окне были одинаковыми.
        """
        base = f"{symbol}:{side}:{idem_hint}" if idem_hint else f"{symbol}:{side}:{int(time.time()//2)}"
        h = int(hashlib.crc32(base.encode("utf-8")) & 0xFFFFFFFF)
        short = self._to_base36(h)
        text = f"t-cai-{short}"
        if len(text) > 28:
            text = text[:28]
        return text

    @staticmethod
    def _to_base36(n: int) -> str:
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        if n == 0:
            return "0"
        s = []
        while n:
            n, r = divmod(n, 36)
            s.append(chars[r])
        return "".join(reversed(s))

    # ------------------------------ API методы ------------------------------

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        self._limiter.acquire_or_raise("market_data")
        try:
            res = self.ccxt.fetch_ticker(symbol)
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._limiter.acquire_or_raise("account")
        try:
            res = self.ccxt.fetch_balance(params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._limiter.acquire_or_raise("orders")
        try:
            res = self.ccxt.fetch_order(order_id, symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_open_orders(self, symbol: Optional[str] = None, since: Optional[int] = None,
                          limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self._limiter.acquire_or_raise("orders")
        try:
            res = self.ccxt.fetch_open_orders(symbol, since, limit, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def cancel_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._limiter.acquire_or_raise("orders")
        try:
            res = self.ccxt.cancel_order(order_id, symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Единая точка генерации clientOrderId для Gate.io:
        - Если в params есть 'text' — уважаем его (вдруг хотим форсировать).
        - Если есть 'idempotency_key' или 'client_id' — используем как hint для стабильности.
        - Иначе генерим на основе (symbol, side, time-bucket).
        """
        self._limiter.acquire_or_raise("orders")
        p = dict(params or {})

        if self.exchange_id == "gateio":
            if "text" not in p:
                idem_hint = p.get("idempotency_key") or p.get("client_id")
                p["text"] = self._gateio_text_from(symbol=symbol, side=side, idem_hint=idem_hint)

        try:
            od = self.ccxt.create_order(symbol=symbol, type=type, side=side, amount=amount, price=price, params=p)
            self.cb.record_success()
            return od
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise
