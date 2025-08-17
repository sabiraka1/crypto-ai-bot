from __future__ import annotations
from typing import Protocol, Callable, Any

class BusProtocol(Protocol):
    def subscribe(self, event_type: str, handler: Callable[[Any], Any]) -> None: ...
    def publish(self, event: Any) -> None: ...
    def health(self) -> dict: ...

from .async_bus import AsyncBus     # продовая реализация
from .bus import Bus                # синхронная простая реализация

__all__ = ["BusProtocol", "AsyncBus", "Bus"]
