# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import binascii
import logging
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
    """
    Gate.io client order id: params['text'] должен начинаться с 't-' и умещаться в ~30 байт.
    Допустимые символы: 0-9 A-Z a-z _ . -
    """
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
    Обёртка над ccxt с простым CircuitBreaker-учётом и per-endpoint rate limiting.
    Совместимая сигнатура create_order(..., type=..., ...), поддержка старого type_.
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
        # Диалект биржи (для легких ветвлений):
        self.exchange_id: str = getattr(self.ccxt, "id", str(name)).lower()
        self.bus = bus
        self.cb = CircuitBreaker(name=f"ccxt:{name}")

        # Per-endpoint limiter — опционально (ожидаем GateIOLimiter или аналог)
        self.limiter = getattr(settings, "limiter", None) or getattr(self.ccxt, "limiter", None)

        # sandbox/spot-only: если у настроек есть такие флаги — уважаем
        try:
            if bool(getattr(settings, "SANDBOX", False)) and hasattr(self.ccxt, "set_sandbox_mode"):
                self.ccxt.set_sandbox_mode(True)
        except Exception:
            pass

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

    # ---- market data / account ----

    def fetch_ticker(self, symbol: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._rl("market_data"):
            raise RateLimitExceeded("market_data rate limit exceeded")
        try:
            res = self.ccxt.fetch_ticker(symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._rl("account"):
            raise RateLimitExceeded("account rate limit exceeded")
        try:
            res = self.ccxt.fetch_balance(params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

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
        """
        Gate spot:
          - market BUY: amount = quote cost, нужен params['createMarketBuyOrderRequiresPrice']=False
          - client order id: params['text'] = 't-...'
        Для других бирж лишние параметры будут проигнорированы.
        """
        if not self._rl("orders"):
            raise RateLimitExceeded("orders rate limit exceeded")

        if (not type) and ("type_" in kwargs):  # совместимость со старой сигнатурой
            type = kwargs["type_"]

        p = dict(params or {})

        # Проставим client-order-id, если не передали
        if "text" not in p and self.exchange_id == "gateio":
            seed = kwargs.get("idempotency_key") or kwargs.get("client_order_id")
            p["text"] = _gateio_text_from(seed)

        # Особенность Gate spot market BUY: amount = QUOTE (cost)
        if self.exchange_id == "gateio" and type == "market" and side.lower() == "buy":
            p.setdefault("createMarketBuyOrderRequiresPrice", False)

        try:
            res = self.ccxt.create_order(symbol, type, side, amount, price, p)
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._rl("orders"):
            raise RateLimitExceeded("orders rate limit exceeded")
        try:
            res = self.ccxt.cancel_order(id, symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._rl("orders"):
            raise RateLimitExceeded("orders rate limit exceeded")
        try:
            res = self.ccxt.fetch_order(id, symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self._rl("orders"):
            raise RateLimitExceeded("orders rate limit exceeded")
        try:
            res = self.ccxt.fetch_open_orders(symbol, since, limit, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise
