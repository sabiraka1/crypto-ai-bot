from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.brokers import to_exchange_symbol, normalize_timeframe
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils import metrics

class PaperExchange(ExchangeInterface):
    def __init__(self, *, latency_ms: int = 50, commission_pct: float = 0.0004):
        self.id = "paper"
        self.latency_ms = int(latency_ms)
        self.commission_pct = float(commission_pct)
        self.cb = CircuitBreaker()

    # --- helpers ---
    def _sleep(self):
        time.sleep(max(0.0, self.latency_ms / 1000.0))

    # --- interface ---
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        ex_symbol = to_exchange_symbol(symbol, self.id)
        tf = normalize_timeframe(timeframe)
        key = f"{self.id}:fetch_ohlcv"

        def _impl():
            self._sleep()
            now = int(time.time() * 1000)
            # dummy candles, strictly increasing
            candles = []
            step = 60_000  # 1m
            for i in range(limit):
                t = now - (limit - i) * step
                o = 10000.0 + i
                h = o * 1.01
                l = o * 0.99
                c = o * 1.001
                v = 1.0
                candles.append([t, o, h, l, c, v])
            return candles

        t0 = time.perf_counter()
        try:
            res = self.cb.call(_impl, key=key, timeout=5.0, fail_threshold=5, open_seconds=8.0)
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.id, "method": "fetch_ohlcv"})
            metrics.inc("broker_requests_total", {"exchange": self.id, "method": "fetch_ohlcv"})
            return res
        except Exception as e:
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.id, "method": "fetch_ohlcv"})
            metrics.inc("broker_errors_total", {"exchange": self.id, "method": "fetch_ohlcv", "type": type(e).__name__})
            raise

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        ex_symbol = to_exchange_symbol(symbol, self.id)
        key = f"{self.id}:fetch_ticker"
        def _impl():
            self._sleep()
            return {"symbol": ex_symbol, "last": 10000.0, "timestamp": int(time.time() * 1000)}
        t0 = time.perf_counter()
        try:
            res = self.cb.call(_impl, key=key, timeout=5.0, fail_threshold=5, open_seconds=8.0)
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.id, "method": "fetch_ticker"})
            metrics.inc("broker_requests_total", {"exchange": self.id, "method": "fetch_ticker"})
            return res
        except Exception as e:
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.id, "method": "fetch_ticker"})
            metrics.inc("broker_errors_total", {"exchange": self.id, "method": "fetch_ticker", "type": type(e).__name__})
            raise

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        ex_symbol = to_exchange_symbol(symbol, self.id)
        key = f"{self.id}:create_order"
        def _impl():
            self._sleep()
            amt = float(amount)
            last = 10000.0
            filled = amt
            cost = filled * last * (1.0 + self.commission_pct)
            return {"id": f"paper_{int(time.time()*1000)}", "symbol": ex_symbol, "status": "closed", "filled": filled, "price": last, "cost": cost, "side": side, "type": type_}
        t0 = time.perf_counter()
        try:
            res = self.cb.call(_impl, key=key, timeout=5.0, fail_threshold=5, open_seconds=8.0)
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.id, "method": "create_order"})
            metrics.inc("broker_requests_total", {"exchange": self.id, "method": "create_order"})
            return res
        except Exception as e:
            dt = int((time.perf_counter() - t0) * 1000)
            metrics.observe("broker_request_ms", dt, {"exchange": self.id, "method": "create_order"})
            metrics.inc("broker_errors_total", {"exchange": self.id, "method": "create_order", "type": type(e).__name__})
            raise

    def fetch_balance(self) -> Dict[str, Any]:
        key = f"{self.id}:fetch_balance"
        def _impl():
            self._sleep()
            return {"USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0}}
        return self.cb.call(_impl, key=key, timeout=5.0, fail_threshold=5, open_seconds=8.0)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        key = f"{self.id}:cancel_order"
        def _impl():
            self._sleep()
            return {"id": order_id, "status": "canceled"}
        return self.cb.call(_impl, key=key, timeout=5.0, fail_threshold=5, open_seconds=8.0)

def from_settings(cfg) -> PaperExchange:
    latency = int(getattr(cfg, "PAPER_LATENCY_MS", 50))
    fee = float(getattr(cfg, "PAPER_COMMISSION_PCT", 0.0004))
    return PaperExchange(latency_ms=latency, commission_pct=fee)
