from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from crypto_ai_bot.core.application.ports import EventBusPort
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus, Event
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus


@runtime_checkable
class _AsyncBusLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> Any: ...
    def on(self, topic: str, handler: Callable[[Event], Awaitable[None]]) -> None: ...


@runtime_checkable
class _RedisBusLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None: ...
    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...


class UnifiedEventBus(EventBusPort):
    """
    Унифицирует интерфейсы разных реализаций шины:
    - AsyncEventBus (работает с Event)
    - RedisEventBus (работает с dict)
    Внешний контракт: publish(dict), on(dict-handler). Возвращает None.
    """

    def __init__(self, implementation: AsyncEventBus | RedisEventBus):
        self._impl = implementation
        self._is_async = isinstance(implementation, AsyncEventBus)

    async def start(self) -> None:
        if hasattr(self._impl, "start"):
            await self._impl.start()

    async def close(self) -> None:
        if hasattr(self._impl, "close"):
            await self._impl.close()

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        if self._is_async:
            impl: _AsyncBusLike = self._impl  # type: ignore[assignment]
            await impl.publish(topic, payload, key=key)
            return
        impl2: _RedisBusLike = self._impl  # type: ignore[assignment]
        await impl2.publish(topic, payload, key=key)

    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        if self._is_async:
            impl: _AsyncBusLike = self._impl  # type: ignore[assignment]

            async def _wrap(evt: Event) -> None:
                await handler(evt.payload)

            impl.on(topic, _wrap)
            return

        impl2: _RedisBusLike = self._impl  # type: ignore[assignment]
        impl2.on(topic, handler)
