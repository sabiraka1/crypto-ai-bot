# src/crypto_ai_bot/core/events/__init__.py
from __future__ import annotations
from typing import Protocol, Callable, Any, Dict

class BusProtocol(Protocol):
    def subscribe(self, event_type: str, handler: Callable[[Any], Any]) -> None: ...
    def publish(self, event: Any) -> None: ...
    def health(self) -> Dict[str, Any]: ...

from .async_bus import AsyncEventBus  # корректный класс
AsyncBus = AsyncEventBus              # алиас для старых импортов

__all__ = ["BusProtocol", "AsyncEventBus", "AsyncBus"]
