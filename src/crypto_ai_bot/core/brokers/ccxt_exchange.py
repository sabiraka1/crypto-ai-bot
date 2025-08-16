from __future__ import annotations

import math
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.brokers.base import ExchangeInterface, ExchangeError, TransientExchangeError, PermanentExchangeError
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils import metrics

def _load_ccxt():
    try:
        import ccxt  # type: ignore
        return ccxt
    except Exception as e:
        raise
        
        # update circuit gauge on error
        try:
            st = self.cb.get_state(self._cb_key)
            metrics.set_gauge("circuit_state", self.cb._state_to_value(st))
        except Exception:
            pass PermanentExchangeError(f"ccxt_not_installed: {e}")

class CcxtExchange(ExchangeInterface):
    """
    CCXT-адаптер с circuit breaker и метриками. Безопасные таймауты и ретраи полагаемся на ccxt.enableRateLimit.
    """
    def __init__(self, client, *, timeout_s: float = 5.0, cb_fail_threshold: int = 5, cb_open_seconds: float = 8.0) -> None:
        self.client = client
        self.cb = CircuitBreaker()
        self.timeout_s = float(timeout_s)
        self.cb_fail_threshold = int(cb_fail_threshold)
        self.cb_open_seconds = float(cb_open_seconds)

    # ---- internal ----
    def _cb_call(self, name: str, fn):
        key = f"ccxt:{self.client.id}:{name}"
        t0 = time.perf_counter()
        def _wrapped():
            return fn()
        try:
            res = self.cb.call(
                _wrapped,
                key=key,
                timeout=self.timeout_s,
                fail_threshold=self.cb_fail_threshold,
                open_seconds=self.cb_open_seconds,
            )
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.client.id, "method": name})
            metrics.inc("broker_requests_total", {"exchange": self.client.id, "method": name})
            return res
        
        # update circuit gauge
        try:
            st = self.cb.get_state(self._cb_key)
            metrics.set_gauge("circuit_state", self.cb._state_to_value(st))
        except Exception:
            pass
        except Exception as e:
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.client.id, "method": name})
            metrics.inc("broker_errors_total", {"exchange": self.client.id, "method": name, "type": type(e).__name__})
            # классификация ошибок
            msg = str(e)
            if "timeout" in msg.lower() or "NetworkError" in msg or "DDoSProtection" in msg:
                raise
        
        # update circuit gauge on error
        try:
            st = self.cb.get_state(self._cb_key)
            metrics.set_gauge("circuit_state", self.cb._state_to_value(st))
        except Exception:
            pass TransientExchangeError(msg)
            raise
        
        # update circuit gauge on error
        try:
            st = self.cb.get_state(self._cb_key)
            metrics.set_gauge("circuit_state", self.cb._state_to_value(st))
        except Exception:
            pass

    # ---- interface ----
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        def _impl():
            return self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return self._cb_call("fetch_ohlcv", _impl)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        def _impl():
            return self.client.fetch_ticker(symbol)
        return self._cb_call("fetch_ticker", _impl)

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        def _impl():
            amt = float(amount)
            px = float(price) if price is not None else None
            if type_ == "market":
                return self.client.create_order(symbol, "market", side, amt)
            return self.client.create_order(symbol, type_, side, amt, px)
        return self._cb_call("create_order", _impl)

    def fetch_balance(self) -> Dict[str, Any]:
        def _impl():
            return self.client.fetch_balance()
        return self._cb_call("fetch_balance", _impl)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        def _impl():
            return self.client.cancel_order(order_id)
        return self._cb_call("cancel_order", _impl)

# Factory
def from_settings(cfg) -> CcxtExchange:
    ccxt = _load_ccxt()
    ex_id = getattr(cfg, "EXCHANGE_ID", "binance")
    klass = getattr(ccxt, ex_id, None)
    if klass is None:
        raise
        
        # update circuit gauge on error
        try:
            st = self.cb.get_state(self._cb_key)
            metrics.set_gauge("circuit_state", self.cb._state_to_value(st))
        except Exception:
            pass PermanentExchangeError(f"exchange_unknown: {ex_id}")
    args = {
        "apiKey": getattr(cfg, "EXCHANGE_KEY", None),
        "secret": getattr(cfg, "EXCHANGE_SECRET", None),
        "password": getattr(cfg, "EXCHANGE_PASSWORD", None),
        "enableRateLimit": True,
        "options": {
            "defaultType": getattr(cfg, "EXCHANGE_DEFAULT_TYPE", "spot"),  # spot|future
        },
        "timeout": int(getattr(cfg, "BROKER_TIMEOUT_S", 5000) * 1000),
    }
    client = klass(args)
    timeout_s = float(getattr(cfg, "BROKER_TIMEOUT_S", 5.0))
    cb_fail = int(getattr(cfg, "CB_FAIL_THRESHOLD", 5))
    cb_open = float(getattr(cfg, "CB_OPEN_SECONDS", 8.0))
    return CcxtExchange(client, timeout_s=timeout_s, cb_fail_threshold=cb_fail, cb_open_seconds=cb_open)


    def get_cb_stats(self) -> dict:
        try:
            return self.cb.get_stats(self._cb_key)
        except Exception:
            return {}
