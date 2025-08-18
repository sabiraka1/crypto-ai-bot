# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import logging
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


class CCXTExchange:
    """
    Обёртка над ccxt с простым CB-учётом.
    """

    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")

        name = exchange_name or getattr(settings, "EXCHANGE", "binance")
        if not hasattr(ccxt, name):
            raise ValueError(f"Unknown ccxt exchange: {name}")

        klass = getattr(ccxt, name)
        self.ccxt = klass({
            "apiKey": getattr(settings, "API_KEY", None),
            "secret": getattr(settings, "API_SECRET", None),
            "enableRateLimit": True,
        })
        self.bus = bus
        self.cb = CircuitBreaker(name=f"ccxt:{name}")

        try:
            self.ccxt.load_markets()
            self.cb.record_success()
        except Exception as e:
            logger.warning("load_markets failed: %s", e)
            self.cb.record_error(_kind_from_exc(e), e)

    # ---- market data ----
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            res = self.ccxt.fetch_ticker(symbol)
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        if (not type) and ("type_" in kwargs):
            type = kwargs["type_"]
        try:
            res = self.ccxt.create_order(symbol, type, side, amount, price, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            res = self.ccxt.cancel_order(id, symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        try:
            res = self.ccxt.fetch_open_orders(symbol, since, limit, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise
