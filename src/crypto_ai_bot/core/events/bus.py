from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, DefaultDict
from collections import defaultdict

Handler = Callable[[ "Event" ], Awaitable[None]]

@dataclass(frozen=True)
class Event:
    topic: str
    payload: Dict[str, Any]
    key: str

class AsyncEventBus:
    """
    Ленивый запуск воркеров: фоновые таски создаются
    ТОЛЬКО когда мы уже внутри работающего event loop
    (в publish()/subscribe()/subscribe_dlq()).
    """

    def __init__(self, *, max_attempts: int = 3, backoff_base_ms: int = 50) -> None:
        self._queue: "asyncio.Queue[Event]" = asyncio.Queue()
        self._subscribers: DefaultDict[str, List[Handler]] = defaultdict(list)
        self._dlq_subscribers: List[Handler] = []
        self._worker: Optional[asyncio.Task] = None
        self._dlq_worker: Optional[asyncio.Task] = None
        self._closed: bool = False
        self._max_attempts = max_attempts
        self._backoff_base_ms = backoff_base_ms

    # --- публичные методы ---

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._ensure_started()
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        try:
            self._subscribers[topic].remove(handler)
        except ValueError:
            pass

    def subscribe_dlq(self, handler: Handler) -> None:
        self._ensure_started()
        self._dlq_subscribers.append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: str) -> None:
        self._ensure_started()
        await self._queue.put(Event(topic=topic, payload=payload, key=key))

    async def close(self) -> None:
        self._closed = True
        # аккуратно останавливаем воркеры (если были запущены)
        for task in (self._worker, self._dlq_worker):
            if task is not None:
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass

    # --- внутреннее ---

    def _ensure_started(self) -> None:
        """Запускает фоновые таски, только если есть активный event loop."""
        if self._worker is not None and self._dlq_worker is not None:
            return
        loop = asyncio.get_running_loop()  # <-- гарантируем, что уже в async-контексте
        if self._worker is None:
            self._worker = loop.create_task(self._run_worker(), name="eventbus-worker")
        if self._dlq_worker is None:
            self._dlq_worker = loop.create_task(self._run_dlq_worker(), name="eventbus-dlq")

    async def _run_worker(self) -> None:
        while not self._closed:
            evt = await self._queue.get()
            handlers = list(self._subscribers.get(evt.topic, ()))
            for h in handlers:
                await self._dispatch_with_retry(h, evt)

    async def _dispatch_with_retry(self, handler: Handler, evt: Event) -> None:
        attempt = 0
        while True:
            try:
                await handler(evt)
                return
            except Exception as exc:
                attempt += 1
                if attempt >= self._max_attempts:
                    await self._emit_dlq(handler, evt, exc)
                    return
                # backoff
                delay = (self._backoff_base_ms * (2 ** (attempt - 1))) / 1000.0
                await asyncio.sleep(delay)

    async def _emit_dlq(self, handler: Handler, evt: Event, exc: Exception) -> None:
        if not self._dlq_subscribers:
            return
        shadow = {
            "topic": evt.topic,
            "key": evt.key,
            "payload": evt.payload,
            "error": str(exc),
            "handler": getattr(handler, "__name__", repr(handler)),
        }
        for h in self._dlq_subscribers:
            try:
                await h(Event(topic="__dlq__", payload=shadow, key=evt.key))
            except Exception:
                pass

    async def _run_dlq_worker(self) -> None:
        # отдельный воркер может не понадобиться; оставлен как задел
        while not self._closed:
            await asyncio.sleep(0.5)
