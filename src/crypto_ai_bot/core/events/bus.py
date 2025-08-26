from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, DefaultDict, Dict, List, Optional

from ...utils.time import now_ms
from ...utils.logging import get_logger

# Метрики — делаем безопасно (no-op, если модуль урезан)
try:
    from ...utils.metrics import inc, timer  # type: ignore
except Exception:  # pragma: no cover
    def inc(*args, **kwargs):  # type: ignore
        return None
    from contextlib import contextmanager
    @contextmanager
    def timer(*args, **kwargs):  # type: ignore
        yield


Handler = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class AsyncEventBus:
    """Асинхронная шина событий с гарантией порядка per-key, ретраями и DLQ."""
    max_attempts: int = 3
    backoff_base_ms: int = 250
    backoff_factor: float = 2.0

    _subs: DefaultDict[str, List[Handler]] = field(default_factory=lambda: defaultdict(list))
    _dlq_handlers: List[Handler] = field(default_factory=list)
    _dlq: List[Dict[str, Any]] = field(default_factory=list)

    _queues: Dict[str, asyncio.Queue] = field(default_factory=dict)         # per-key очереди
    _workers: Dict[str, asyncio.Task] = field(default_factory=dict)         # per-key воркеры

    _log = get_logger("events.bus")

    # -------------------- API --------------------

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def subscribe_dlq(self, handler: Handler) -> None:
        """Подписка на обработку событий, которые дошли до DLQ."""
        self._dlq_handlers.append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: Optional[str] = None) -> None:
        """Публикация с гарантией порядка для каждого ключа (topic:key)."""
        inc("events_published_total", {"topic": topic})
        qkey = f"{topic}:{key}" if key else topic
        if qkey not in self._queues:
            self._queues[qkey] = asyncio.Queue()
            self._workers[qkey] = asyncio.create_task(self._process_queue(qkey, topic), name=f"bus-{qkey}")
        await self._queues[qkey].put(payload)

    async def shutdown(self) -> None:
        """Останавливает внутренних воркеров (используй при graceful shutdown)."""
        for t in list(self._workers.values()):
            t.cancel()
        await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._queues.clear()

    def dlq_size(self) -> int:
        return len(self._dlq)

    def get_dlq(self) -> List[Dict[str, Any]]:
        return list(self._dlq)

    # -------------------- internals --------------------

    async def _process_queue(self, qkey: str, topic: str) -> None:
        queue = self._queues[qkey]
        while True:
            payload = await queue.get()
            handlers = self._subs.get(topic, [])
            if not handlers:
                queue.task_done()
                continue
            for h in handlers:
                await self._invoke_with_retry(h, payload, topic)
            queue.task_done()

    async def _invoke_with_retry(self, handler: Handler, payload: Dict[str, Any], topic: str) -> None:
        attempts = 0
        while True:
            attempts += 1
            try:
                with timer("event_handler_ms", {"topic": topic}):
                    await handler(payload)
                inc("events_handled_total", {"topic": topic, "status": "success"})
                return
            except Exception as exc:  # noqa: BLE001 — хотим ловить любые
                if attempts >= self.max_attempts:
                    await self._send_to_dlq(topic, payload, str(exc))
                    inc("events_handled_total", {"topic": topic, "status": "dlq"})
                    self._log.error("event_handler_failed_dlq", extra={"topic": topic, "error": str(exc)})
                    return
                backoff = self.backoff_base_ms * (self.backoff_factor ** (attempts - 1))
                await asyncio.sleep(backoff / 1000.0)

    async def _send_to_dlq(self, topic: str, payload: Dict[str, Any], error: str) -> None:
        evt = {"original_topic": topic, "payload": payload, "error": error, "timestamp": now_ms()}
        self._dlq.append(evt)
        for handler in list(self._dlq_handlers):
            try:
                await handler(evt)
            except Exception:
                # обработчики DLQ не должны валить шину
                pass
