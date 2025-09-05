from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from crypto_ai_bot.core.application.ports import EventBusPort
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus, Event
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus

__all__ = ["UnifiedEventBus"]


@runtime_checkable
class _AsyncBusLike(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def close(self) -> None: ...
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> Any: ...
    def on(self, topic: str, handler: Callable[[Event], Awaitable[None]]) -> None: ...
    # опционально: префиксные подписки
    def on_wildcard(self, pattern: str, handler: Callable[[Event], Awaitable[None]]) -> None: ...  # type: ignore[empty-body]


@runtime_checkable
class _RedisBusLike(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def close(self) -> None: ...
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None: ...
    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...
    def on_wildcard(self, pattern: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...  # type: ignore[empty-body]


class UnifiedEventBus(EventBusPort):
    """
    Унифицирует интерфейсы разных реализаций шины:
      - AsyncEventBus (работает с Event)
      - RedisEventBus (работает с dict)
    Внешний контракт: publish(dict), on(dict-handler), on_wildcard(dict-handler).
    Методы жизненного цикла: start(), stop(); close() — синоним stop().
    """

    def __init__(self, implementation: AsyncEventBus | RedisEventBus):
        self._impl = implementation
        self._is_async = isinstance(implementation, AsyncEventBus)

    # ---------- lifecycle ----------

    async def start(self) -> None:
        # поддерживаем оба варианта у реализации
        if hasattr(self._impl, "start"):
            await getattr(self._impl, "start")()

    async def stop(self) -> None:
        # сначала пытаемся корректно остановить
        if hasattr(self._impl, "stop"):
            await getattr(self._impl, "stop")()
            return
        # если stop нет — пробуем close
        if hasattr(self._impl, "close"):
            await getattr(self._impl, "close")()

    async def close(self) -> None:
        # совместимость: close() == stop()
        await self.stop()

    # ---------- publish / subscribe ----------

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

    # опционально поддерживаем wildcard-подписки, если реализация их умеет
    def on_wildcard(self, pattern: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        if not hasattr(self._impl, "on_wildcard"):
            return

        if self._is_async:
            impl: _AsyncBusLike = self._impl  # type: ignore[assignment]

            async def _wrap(evt: Event) -> None:
                await handler(evt.payload)

            # type: ignore[attr-defined]
            impl.on_wildcard(pattern, _wrap)  # noqa: B019
            return

        impl2: _RedisBusLike = self._impl  # type: ignore[assignment]
        # type: ignore[attr-defined]
        impl2.on_wildcard(pattern, handler)  # noqa: B019
