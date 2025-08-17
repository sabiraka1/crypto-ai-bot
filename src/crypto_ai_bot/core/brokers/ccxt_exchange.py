from __future__ import annotations

from decimal import Decimal
from typing import Optional

from crypto_ai_bot.core.events import BusProtocol
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics

# Заглушка-адаптер: сохраняет совместимость интерфейса и публикует события.
# Если у тебя уже есть реальный код на ccxt — оставь его, просто добавь set_bus и publish() в create_order/cancel.
class CcxtExchange:
    def __init__(self) -> None:
        self._bus: Optional[BusProtocol] = None

    @classmethod
    def from_settings(cls, cfg: Settings) -> "CcxtExchange":
        return cls()

    def set_bus(self, bus: Optional[BusProtocol]) -> None:
        self._bus = bus

    def fetch_ticker(self, symbol: str) -> dict:
        metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "fetch_ticker"})
        # Здесь должен быть вызов ccxt. Для health достаточно заглушки:
        return {"symbol": symbol, "price": 50_000.0}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "fetch_ohlcv"})
        raise NotImplementedError("Wire with real ccxt implementation")

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None) -> dict:
        metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "create_order"})
        # здесь — реальный вызов ccxt, ниже — публикации
        if self._bus:
            try:
                self._bus.publish({"type": "OrderSubmitted", "symbol": symbol, "side": side, "amount": str(amount)})
                self._bus.publish({"type": "OrderFilled", "symbol": symbol, "side": side, "amount": str(amount), "price": str(price or Decimal("0"))})
            except Exception:
                pass
        return {"id": "ccxt_order_1", "status": "filled"}

    def cancel_order(self, order_id: str) -> dict:
        metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "cancel_order"})
        if self._bus:
            try:
                self._bus.publish({"type": "OrderCanceled", "order_id": order_id})
            except Exception:
                pass
        return {"id": order_id, "status": "canceled"}

    def fetch_balance(self) -> dict:
        metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "fetch_balance"})
        raise NotImplementedError("Wire with real ccxt implementation")

    def close(self) -> None:  # pragma: no cover
        pass
