from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

# Базовые интерфейсы (как у тебя в проекте)
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus, Event
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus


@runtime_checkable
class EventBusPort(Protocol):
    """Единый контракт для шины событий во всей системе."""

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None: ...
    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...


class UnifiedEventBus(EventBusPort):
    """
    Адаптер, унифицирующий интерфейсы разных реализаций шины:
    - AsyncEventBus (работает с Event)
    - RedisEventBus (работает с dict)
    Внешне всегда publish(dict) и on(dict-handler), возвращает None.
    """

    def __init__(self, implementation: AsyncEventBus | RedisEventBus):
        self._impl = implementation
        self._is_async = isinstance(implementation, AsyncEventBus)

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        if self._is_async:
            # AsyncEventBus может возвращать Event/Dict — стандартизируем до None
            await self._impl.publish(topic, payload, key=key)
            return
        # RedisEventBus уже возвращает None
        await self._impl.publish(topic, payload, key=key)

    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        if self._is_async:
            async def _wrap(evt: Event) -> None:
                # Извлекаем только payload из Event для handler
                await handler(evt.payload)

            self._impl.on(topic, _wrap)
            return

        # RedisEventBus – уже dict
        # Для RedisEventBus нужен другой wrapper
        async def _redis_wrap(data: Any) -> None:
            await handler(data)
    
        self._impl.on(topic, _redis_wrap)

    async def start(self) -> None:
        if hasattr(self._impl, "start"):
            await self._impl.start()

    async def close(self) -> None:
        if hasattr(self._impl, "close"):
            await self._impl.close()

    # Проксируем остальное без «магии»
    def __getattr__(self, name: str) -> Any:  # pragma: no cover
        return getattr(self._impl, name)