# src/crypto_ai_bot/core/events/__init__.py
from .bus import Bus
from .async_bus import AsyncBus

__all__ = ["Bus", "AsyncBus"]

def get_bus(kind: str = "sync", **kwargs):
    """
    Фабрика для создания шины.
    kind: "sync" | "async"
    kwargs пробрасываются в конструктор.
    """
    if kind == "sync":
        return Bus(**kwargs)
    elif kind == "async":
        return AsyncBus(**kwargs)
    raise ValueError(f"unknown bus kind: {kind!r}")
