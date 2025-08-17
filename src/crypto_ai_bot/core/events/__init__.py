from __future__ import annotations
from typing import Protocol, Callable, Any

# Единый контракт — чтобы и sync, и async реализации выглядели одинаково
class BusProtocol(Protocol):
    def subscribe(self, event_type: str, handler: Callable[[Any], Any]) -> None: ...
    def publish(self, event: Any) -> None: ...
    def health(self) -> dict: ...

# Две реализации: синхронная и асинхронная
from .async_bus import AsyncBus     # для прод-рантайма (FastAPI/оркестратор/брокеры)
from .bus import Bus                # для юнит-тестов, простых утилит

__all__ = ["BusProtocol", "AsyncBus", "Bus"]
