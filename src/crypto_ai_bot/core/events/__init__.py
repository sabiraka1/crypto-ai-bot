# src/crypto_ai_bot/core/events/__init__.py
from .bus import AsyncEventBus as AsyncEventBus
AsyncBus = AsyncEventBus  # alias для обратной совместимости

__all__ = ["AsyncEventBus", "AsyncBus"]
