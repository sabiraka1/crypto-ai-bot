# src/crypto_ai_bot/core/events/__init__.py
from __future__ import annotations
from typing import Any, Callable, Protocol

# --- BusProtocol: берём из bus.py, при отсутствии даём безопасный fallback ---
try:
    # если в bus.py объявлен протокол — используем его
    from .bus import BusProtocol as _BusProtocol  # type: ignore
except Exception:
    # fallback-протокол (минимальный контракт)
    class _BusProtocol(Protocol):
        def subscribe(self, event_type: str, handler: Callable[[Any], Any]) -> None: ...
        def publish(self, event: Any) -> None: ...
        def health(self) -> dict: ...

BusProtocol = _BusProtocol  # публичное имя

# --- Синхронная реализация (если присутствует) ---
try:
    from .bus import Bus  # type: ignore
except Exception:
    # ни на что не влияет: просто не экспортируем Bus, если его нет
    pass

# --- Асинхронная продовая реализация ---
from .async_bus import AsyncEventBus  # <- корректное имя класса

# Обратная совместимость со старым неймингом:
AsyncBus = AsyncEventBus

# --- Фабрика шины (опционально, если есть) ---
# Поддержим оба варианта имени, чтобы не ломать существующие импорты.
try:
    from .factory import create_bus  # type: ignore
except Exception:
    try:
        from .factory import build_bus as create_bus  # type: ignore
    except Exception:
        pass

# --- Публичный API пакета ---
__all__ = [name for name in (
    "BusProtocol",
    "Bus",
    "AsyncEventBus",
    "AsyncBus",
    "create_bus",
) if name in globals()]
