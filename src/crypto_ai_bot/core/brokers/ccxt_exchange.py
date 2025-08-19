from __future__ import annotations

import binascii
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional

from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger("brokers.ccxt_exchange")

try:
    import ccxt
    from ccxt.base.errors import (
        DDoSProtection, RateLimitExceeded, ExchangeNotAvailable, NetworkError,
        RequestTimeout, AuthenticationError, PermissionDenied,
        InvalidOrder, InsufficientFunds, OrderNotFound
    )
except Exception:  # pragma: no cover
    ccxt = None


def _kind_from_exc(e: Exception) -> str:
    if isinstance(e, (RateLimitExceeded, DDoSProtection)):
        return "rate_limit"
    if isinstance(e, (RequestTimeout, NetworkError, ExchangeNotAvailable)):
        return "network"
    if isinstance(e, (AuthenticationError, PermissionDenied)):
        return "auth"
    if isinstance(e, (InvalidOrder, InsufficientFunds, OrderNotFound)):
        return "order"
    return "other"


_SAFE_TEXT_RE = re.compile(r"[0-9A-Za-z_.-]+")


def _gateio_text_from(seed: Optional[str] = None) -> str:
    ts = int(time.time() * 1000)
    body = f"cai{format(ts % 10**9, 'x')}"
    if seed:
        h = format(binascii.crc32(seed.encode("utf-8")) & 0xFFFF_FFFF, "x")
        body = f"{body}{h}"
    body = body[:28]
    if not _SAFE_TEXT_RE.fullmatch(body):
        body = re.sub(r"[^0-9A-Za-z_.-]", ".", body)[:28]
    return f"t-{body}"


class CCXTExchange:
    """
    Обёртка над ccxt с CircuitBreaker и per-endpoint rate limiting.
    Важные особенности:
      - При OPEN состоянии брекера — немедленно отклоняем вызов (fail-fast).
      - При RateLimit/Network — выполняем несколько ретраев с экспоненциальным бэкоффом + джиттер.
      - Gate spot market BUY: amount = quote cost, params['createMarketBuyOrderRequiresPrice']=False.
      - Gate client order id: params['text'] = 't-...'
    """

    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")

        name = exchange_name or getattr(settings, "EXCHANGE", "gateio")
        if not hasattr(ccxt, name):
            raise ValueError(f"Unknown ccxt exchange: {name}")

        klass = getattr(ccxt, name)
        self.ccxt = klass({
            "apiKey": getattr(settings, "API_KEY", None),
            "secret": getattr(settings, "API_SECRET", None),
            "enableRateLimit": True,
        })
        self.exchange_id: str = getattr(self.ccxt, "id", str(name)).lower()
        self.bus = bus

        # Circuit breaker: параметры можно пробросить из Settings при желании
        self.cb = CircuitBreaker(
            name=f"ccxt:{name}",
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            open_timeout_sec=float(getattr(settings, "CB_OPEN_TIMEOUT_SEC", 30.0)),
            half_open_max_calls=int(getattr(settings, "CB_HALF_OPEN_CALLS", 1)),
            window_sec=float(getattr(settings, "CB_WINDOW_SEC", 60.0)),
        )

        # Per-endpoint limiter — опционально (ожидаем GateIOLimiter или аналог)
        self.limiter = getattr(settings, "limiter", None) or getattr(self.ccxt, "limiter", None)

        try:
            self.ccxt.load_markets()
            self.cb.record_success()
        except Exception as e:
            logger.warning("load_markets failed: %r", e)
            self.cb.record_error(_kind_from_exc(e), e)

    # ---- helpers ----

    def _rl(self, bucket: str) -> bool:
        lim = self.limiter
        if lim is None:
            return True
        try:
            if hasattr(lim, "try_acquire"):
                return bool(lim.try_acquire(bucket))
        except Exception:
            return True
        return True

    def _with_retries(self, fn, *args, bucket: str, **kwargs):
        """
        Универсальная обёртка с брекером и бэкоффом.
        """
        # fail-fast, если брекер открыт и не настало half-open окно
        if not self.cb.allow():
            raise RateLimitExceeded("circuit_open")

        # экспоненц. бэкофф + джиттер
        max_attempts = int(getattr(self.ccxt, "_max_attempts", 4))
        base = 0.25
        for attempt in range(1, max_attempts + 1):
            # per-endpoint rate limit
            if not self._rl(bucket):
                # быстрый короткий сон, чтобы не лупить впустую
                time.sleep(0.05)
                continue
            try:
                res = fn(*args, **kwargs)
                self.cb.record_success()
                return res
            except Exception as e:
                kind = _kind_from_exc(e)
                self.cb.record_error(kind, e)
                # на auth/invalid order — ретраить бессмысленно
                if kind in ("auth", "order"):
                    raise
                # на открытый брекер — сразу выходим
                if self.cb.state() == "open":
                    raise
                # RateLimit/Network — backoff
                if attempt >= max_attempts:
                    raise
                # jitter 20%
                sleep_s = base * (2 ** (attempt - 1))
                sleep_s *= (0.8 + 0.4 * random.random())
                time.sleep(min(2.5, sleep_s))

    # ---- market data / account ----

    def fetch_ticker(self, symbol: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries(self.ccxt.fetch_ticker, symbol, params or {}, bucket="market_data")

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries(self.ccxt.fetch_balance, params or {}, bucket="account")

    # ---- orders ----

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        p = dict(params or {})
        if "text" not in p and self.exchange_id == "gateio":
            seed = kwargs.get("idempotency_key") or kwargs.get("client_order_id")
            p["text"] = _gateio_text_from(seed)
        if self.exchange_id == "gateio" and type == "market" and side.lower() == "buy":
            p.setdefault("createMarketBuyOrderRequiresPrice", False)
        return self._with_retries(self.ccxt.create_order, symbol, type, side, amount, price, p, bucket="orders")

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries(self.ccxt.cancel_order, id, symbol, params or {}, bucket="orders")

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries(self.ccxt.fetch_order, id, symbol, params or {}, bucket="orders")

    def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return self._with_retries(self.ccxt.fetch_open_orders, symbol, since, limit, params or {}, bucket="orders")
