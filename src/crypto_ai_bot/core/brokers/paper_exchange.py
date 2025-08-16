from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.brokers.base import ExchangeInterface, ExchangeError
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils import metrics

@dataclass
class _PaperOrder:
    id: str
    symbol: str
    side: str
    type: str
    amount: Decimal
    price: Optional[Decimal]
    ts: float

class PaperExchange(ExchangeInterface):
    """
    Простая paper-реализация с обёрткой circuit breaker и метриками.
    Не хранит реальный ордербук — имитирует ответ брокера.
    """
    def __init__(self, *, latency_ms: int = 50, fee_pct: float = 0.06, timeout_s: float = 2.0,
                 cb_fail_threshold: int = 4, cb_open_seconds: float = 5.0) -> None:
        self.latency_ms = int(latency_ms)
        self.fee_pct = float(fee_pct)  # bps (0.06 = 6 bps = 0.06%)
        self.timeout_s = float(timeout_s)
        self.cb = CircuitBreaker()
        self.cb_fail_threshold = int(cb_fail_threshold)
        self.cb_open_seconds = float(cb_open_seconds)
        self._orders: Dict[str, _PaperOrder] = {}
        self._order_seq = 0

    # ---- helpers ----
    def _sleep(self):
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000.0)

    def _cb_call(self, name: str, fn):
        return self.cb.call(
            fn,
            key=f"paper:{name}",
            timeout=self.timeout_s,
            fail_threshold=self.cb_fail_threshold,
            open_seconds=self.cb_open_seconds,
        )

    # ---- interface ----
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        def _impl():
            self._sleep()
            # Минимальный заглушечный ряд (unix_ms, open, high, low, close, volume)
            now = int(time.time() * 1000)
            base = 50000.0
            rows = []
            for i in range(limit):
                t = now - (limit - i) * 60_000
                o = base * (1 + (i % 10) / 1000.0)
                c = o * (1 + ((i % 5) - 2) / 500.0)
                h = max(o, c) * 1.001
                l = min(o, c) * 0.999
                v = 1.0 + (i % 3)
                rows.append([t, o, h, l, c, v])
            return rows
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_ohlcv"})
        return self._cb_call("fetch_ohlcv", _impl)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        def _impl():
            self._sleep()
            px = 50000.0
            spread = px * 0.0008  # 8 bps
            return {"symbol": symbol, "last": px, "bid": px - spread/2, "ask": px + spread/2, "ts": int(time.time()*1000)}
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_ticker"})
        return self._cb_call("fetch_ticker", _impl)

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        def _impl():
            self._sleep()
            self._order_seq += 1
            oid = f"paper-{self._order_seq}"
            ord_obj = _PaperOrder(id=oid, symbol=symbol, side=side, type=type_, amount=Decimal(str(amount)), price=price, ts=time.time())
            self._orders[oid] = ord_obj
            return {"id": oid, "symbol": symbol, "side": side, "type": type_, "amount": float(amount), "price": float(price) if price else None}
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "create_order"})
        return self._cb_call("create_order", _impl)

    def fetch_balance(self) -> Dict[str, Any]:
        def _impl():
            self._sleep()
            return {"USDT": {"free": 10_000.0, "used": 0.0}}
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_balance"})
        return self._cb_call("fetch_balance", _impl)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        def _impl():
            self._sleep()
            if order_id in self._orders:
                del self._orders[order_id]
                return {"id": order_id, "status": "canceled"}
            raise ExchangeError("order_not_found")
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "cancel_order"})
        return self._cb_call("cancel_order", _impl)

# Factory helper
def from_settings(cfg) -> PaperExchange:
    return PaperExchange(
        latency_ms = int(getattr(cfg, "PAPER_LATENCY_MS", 50)),
        fee_pct = float(getattr(cfg, "PAPER_FEE_BPS", 6)) / 100.0,
        timeout_s = float(getattr(cfg, "BROKER_TIMEOUT_S", 2.0)),
        cb_fail_threshold = int(getattr(cfg, "CB_FAIL_THRESHOLD", 4)),
        cb_open_seconds = float(getattr(cfg, "CB_OPEN_SECONDS", 5.0)),
    )
