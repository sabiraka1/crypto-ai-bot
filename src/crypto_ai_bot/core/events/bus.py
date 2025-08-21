from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, DefaultDict
from collections import defaultdict

from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.logging import get_logger


EventHandler = Callable[['Event'], Awaitable[None]]


@dataclass(slots=True)
class Event:
    topic: str
    key: str | None
    payload: dict[str, Any]
    ts_ms: int
    correlation_id: str | None = None


class AsyncEventBus:
    """Асинхронная шина событий: in-memory очередь, порядок по ключу (per-key ordering), DLQ."""

    def __init__(self, *, max_retries: int = 3) -> None:
        self._log = get_logger("event_bus")
        self._handlers: DefaultDict[str, list[EventHandler]] = defaultdict(list)
        self._queues: dict[tuple[str, str | None], asyncio.Queue[Event]] = {}
        self._workers: dict[tuple[str, str | None], asyncio.Task[None]] = {}
        self._dlq: list[Event] = []
        self._max_retries = int(max_retries)
        self._closed = False

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Подписка обработчика на топик. Порядок вызова = порядок подписки."""
        self._handlers[topic].append(handler)

    async def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None, correlation_id: str | None = None) -> None:
        """Публикация события: кладём в очередь, гарантируем порядок для одного key."""
        if self._closed:
            raise RuntimeError("EventBus is closed")
        evt = Event(topic=topic, key=key, payload=payload, ts_ms=now_ms(), correlation_id=correlation_id)
        qkey = (topic, key)
        q = self._queues.get(qkey)
        if q is None:
            q = asyncio.Queue()
            self._queues[qkey] = q
            self._workers[qkey] = asyncio.create_task(self._worker(qkey))
        await q.put(evt)

    def get_dlq(self) -> list[Event]:
        return list(self._dlq)

    async def close(self) -> None:
        self._closed = True
        # Останавливаем воркеры корректно
        for q in self._queues.values():
            await q.put(None)  # type: ignore[arg-type]
        await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._queues.clear()

    async def _worker(self, qkey: tuple[str, str | None]) -> None:
        topic, _ = qkey
        q = self._queues[qkey]
        while True:
            evt = await q.get()
            if evt is None:  # сигнал остановки
                break
            handlers = self._handlers.get(topic, [])
            if not handlers:
                # Никто не подписан — просто проглатываем
                continue
            for h in handlers:
                ok = False
                attempt = 0
                while not ok and attempt < self._max_retries:
                    attempt += 1
                    try:
                        await h(evt)
                        ok = True
                    except Exception as e:  # noqa: BLE001
                        if attempt >= self._max_retries:
                            self._log.error(f"Handler failed; to DLQ: {e}")
                            self._dlq.append(evt)
                        else:
                            await asyncio.sleep(0.05 * attempt)