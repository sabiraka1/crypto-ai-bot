# src/crypto_ai_bot/core/events/__init__.py
from __future__ import annotations
from typing import Protocol, Callable, Any, Dict

# Минимальный публичный контракт шины событий.
# Нужен только для типовой совместимости (runtime-классы ниже).
class BusProtocol(Protocol):
    def subscribe(self, event_type: str, handler: Callable[[Any], Any]) -> None: ...
    def publish(self, event: Any) -> None: ...
    def health(self) -> Dict[str, Any]: ...

# Экспортируем только продовую реализацию, чтобы не ловить круговые импорты.
from .async_bus import AsyncEventBus

# Обратная совместимость со старым именем:
AsyncBus = AsyncEventBus

__all__ = ["BusProtocol", "AsyncEventBus", "AsyncBus"]
