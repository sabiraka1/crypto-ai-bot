from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from crypto_ai_bot.core.events import BusProtocol
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics

# Минимальная paper-имплементация (для событий и /health достаточно)
@dataclass
class _Order:
    id: str
    symbol: str
    side: str
    type: str
    amount: Decimal
    price: Optional[Decimal]
    ts: float


class PaperExchange:
    def __init__(self) -> None:
        self._bus: Optional[BusProtocol] = None
        self._orders: Dict[str, _Order] = {}
        self._balances: Dict[str, Any] = {"USDT": {"free": 10_000, "used": 0, "total": 10_000}}

    @classmethod
    def from_settings(cls, cfg: Settings) -> "PaperExchange":
        return cls()

    def set_bus(self, bus: Optional[BusProtocol]) -> None:
        self._bus = bus

    # ───────────────────────────────────── API ─────────────────────────────────────

    def fetch_ticker(self, symbol: str) -> dict:
        # Детирминированный «тикер»
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_ticker"})
        return {"symbol": symbol, "price": 50_000.0, "ts": int(time.time() * 1000)}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_ohlcv"})
        now = int(time.time() * 1000)
        # простая «ступенька» OHLCV
        out: list[list[float]] = []
        base = 50_000.0
        for i in range(limit):
            t = now - (limit - i) * 60_000
            o = base + i * 5
            h = o + 10
            l = o - 10
            c = o + 2
            v = 1.0
            out.append([t, o, h, l, c, v])
        return out

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None) -> dict:
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "create_order"})
        order_id = f"paper_{int(time.time() * 1e6)}"
        order = _Order(order_id, symbol, side, type_, amount, price, time.time())
        self._orders[order_id] = order

        # Публикуем события, если подключена шина
        if self._bus:
            try:
                self._bus.publish({"type": "OrderSubmitted", "order_id": order_id, "symbol": symbol, "side": side, "amount": str(amount)})
                self._bus.publish({"type": "OrderFilled", "order_id": order_id, "symbol": symbol, "side": side, "amount": str(amount), "price": str(price or Decimal("0"))})
            except Exception:
                pass

        return {"id": order_id, "status": "filled", "symbol": symbol, "side": side, "amount": str(amount), "price": str(price or Decimal("0"))}

    def cancel_order(self, order_id: str) -> dict:
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "cancel_order"})
        self._orders.pop(order_id, None)
        if self._bus:
            try:
                self._bus.publish({"type": "OrderCanceled", "order_id": order_id})
            except Exception:
                pass
        return {"id": order_id, "status": "canceled"}

    def fetch_balance(self) -> dict:
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_balance"})
        return self._balances

    # На будущее – аккуратное закрытие
    def close(self) -> None:  # pragma: no cover
        pass
