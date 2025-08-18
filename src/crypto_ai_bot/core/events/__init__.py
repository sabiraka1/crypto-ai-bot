# src/crypto_ai_bot/core/events/__init__.py
from __future__ import annotations
from typing import Protocol, Callable, Any

class BusProtocol(Protocol):
    def subscribe(self, event_type: str, handler: Callable[[Any], Any]) -> None: ...
    def publish(self, event: Any) -> None: ...
    def health(self) -> dict: ...

# Синхронная простая реализация
from .bus import Bus

# Асинхронная продовая реализация
from .async_bus import AsyncEventBus

# Обратная совместимость: старый нейминг (если где-то ещё используется)
AsyncBus = AsyncEventBus

__all__ = ["BusProtocol", "AsyncEventBus", "AsyncBus", "Bus"]
