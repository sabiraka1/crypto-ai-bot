from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.retry import retry, is_retryable_ccxt  # NEW

logger = logging.getLogger("brokers.ccxt_exchange")

try:
    import ccxt
    from ccxt.base.errors import (
        DDoSProtection,
        RateLimitExceeded,
        ExchangeNotAvailable,
        NetworkError,
        RequestTimeout,
        AuthenticationError,
        PermissionDenied,
        InvalidOrder,
        InsufficientFunds,
        OrderNotFound,
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


def _is_spot_market(ex: Any, symbol: str) -> bool:
    """
    Возвращает True, если символ относится к spot.
    Пытаемся читать из ex.markets[symbol] -> {'spot': True} или type == 'spot'.
    """
    try:
        markets = getattr(ex, "markets", None)
        if markets and symbol in markets:
            m = markets[symbol] or {}
            if m.get("spot") is True:
                return True
            if (m.get("type") or "").lower() == "spot":
                return True
    except Exception:
        pass
    return False


def _merge_params(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if a:
        out.update(a)
    if b:
        out.update(b)
    return out


def _derive_coid(symbol: str, side: str, amount: float) -> str:
    """
    Фолбэк на случай, если clientOrderId не передали снаружи:
    короткий детерминированный идентификатор (на минутном бакете).
    """
    bucket = int(time.time() // 60)
    raw = f"coid:{symbol}|{side}|{round(amount, 8)}|{bucket}"
    # CCXT/биржи часто ограничивают длину; укоротим до 32 символов.
    return raw[:32]


class CCXTExchange:
    """
    Обёртка над ccxt с простым CircuitBreaker-учётом.
    Совместимая сигнатура create_order(..., type=..., ...), поддержка старого type_.
    """

    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")

        name = exchange_name or getattr(settings, "EXCHANGE", "binance")
        if not hasattr(ccxt, name):
            raise ValueError(f"Unknown ccxt exchange: {name}")

        klass = getattr(ccxt, name)
        self.ccxt = klass(
            {
                "apiKey": getattr(settings, "API_KEY", None),
                "secret": getattr(settings, "API_SECRET", None),
                "enableRateLimit": True,
            }
        )
        self.bus = bus
        self.cb = CircuitBreaker(name=f"ccxt:{name}")

        try:
            self.ccxt.load_markets()
            self.cb.record_success()
        except Exception as e:
            logger.warning("load_markets failed: %s", e)
            self.cb.record_error(_kind_from_exc(e), e)

    # ---- market data ----
    @retry(max_attempts=5, backoff_base=0.4, metric_prefix="ccxt", retry_if=is_retryable_ccxt)
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            res = self.ccxt.fetch_ticker(symbol)
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    @retry(max_attempts=5, backoff_base=0.4, metric_prefix="ccxt", retry_if=is_retryable_ccxt)
    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            res = self.ccxt.fetch_balance(params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    # ---- orders ----
    @retry(max_attempts=5, backoff_base=0.5, metric_prefix="ccxt", retry_if=is_retryable_ccxt)
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
        Создание ордера с биржевой идемпотентностью:
        - требуем spot-рынок
        - проставляем clientOrderId/text (если не пришёл извне)
        """
        if (not type) and ("type_" in kwargs):
            type = kwargs["type_"]

        # Только spot
        if not _is_spot_market(self.ccxt, symbol):
            raise ValueError(f"spot_only: {symbol}")

        # Биржевая идемпотентность: берём из params/kwargs или строим фолбэк
        p = dict(params or {})
        coid = p.get("clientOrderId") or p.get("text") or kwargs.get("clientOrderId") or kwargs.get("client_order_id")
        if not coid:
            coid = _derive_coid(symbol, side, float(amount))
        # Широкая совместимость: и clientOrderId, и text (например, gate.io использует 'text')
        p = _merge_params(p, {"clientOrderId": coid, "text": coid})

        try:
            res = self.ccxt.create_order(symbol, type, side, amount, price, p)
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    @retry(max_attempts=5, backoff_base=0.4, metric_prefix="ccxt", retry_if=is_retryable_ccxt)
    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            res = self.ccxt.cancel_order(id, symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    @retry(max_attempts=5, backoff_base=0.4, metric_prefix="ccxt", retry_if=is_retryable_ccxt)
    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            res = self.ccxt.fetch_order(id, symbol, params or {})
            self.cb.record_success()
            return res
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    @retry(max_attempts=5, backoff_base=0.4, metric_prefix="ccxt", retry_if=is_retryable_ccxt)
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
