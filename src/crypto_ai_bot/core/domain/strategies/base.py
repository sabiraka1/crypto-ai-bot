from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Side = Literal["buy", "sell", "hold"]


@dataclass(frozen=True)
class Signal:
    """
    Унифицированный выход стратегии:
      - side: buy/sell/hold
      - confidence: 0..1 (для приоритезации/фильтров)
      - reason: произвольное пояснение (для логов/алертов)
    """

    side: Side
    confidence: float = 0.0
    reason: str | None = None


class BaseStrategy(Protocol):
    """
    Контракт стратегии, не привязанный к конкретному брокеру/хранилищу.
    """

    async def on_tick(self, *, symbol: str, broker: Any, storage: Any, bus: Any) -> Signal | None:
        """
        Периодический вызов/тик. Возвращает торговый сигнал или None.
        """
        ...

    async def on_fill(self, *, order: dict[str, Any]) -> None:
        """
        Событие частичного/полного исполнения ордера.
        """
        ...
