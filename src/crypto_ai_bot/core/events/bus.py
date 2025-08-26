from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, DefaultDict, Dict, List, Optional

from ...utils.logging import get_logger
from ...utils.time import now_ms

# Метрики — делаем необязательными (no-op, если модуль недоступен)
try:
    from ...utils.metrics import inc, timer
except Exception:
    def inc(*args, **kwargs):  # type: ignore
        return None
    @contextmanager
    def timer(*args, **kwargs):  # type: ignore
        yield

Handler = Callable[[Dict[str, Any]], Awaitable[None]]

_log = get_logger("events.bus")


@dataclass
class AsyncEventBus:
    """Асинхронная событийная шина с:
       - per-key ordering (очередь/воркер на ключ)
       - retry + экспоненциальный backoff
       - DLQ (dead-letter queue) c подписчиками
    """
    max_attempts: int = 3
    backoff_base_ms: int = 250
    backoff_factor: float = 2.0

    # topic -> [handlers]
    _subs: DefaultDict[str, List[Handler]] = field(default_factory=lambda: defaultdict(list))
    # dlq subscribers
    _dlq_handlers: List[Handler] = field(default_factory=list)
    _dlq: List[Dict[str, Any]] = field(default_factory=list)

    # per-key очереди и воркеры
    _queues: Dict[str, asyncio.Queue] = field(default_factory=dict)
    _workers: Dict[str, asyncio.Task] = field(default_factory=dict)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def subscribe_dlq(self, handler: Handler) -> None:
        """Подписка на DLQ события (не должна кидать исключений)."""
        self._dlq_handlers.append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: Optional[str] = None) -> None:
        """Публикация события. Для одинакового (topic, key) сохраняется порядок."""
        inc("events_total", {"topic": topic})
        queue_key = f"{topic}:{key}" if key else topic

        if queue_key not in self._queues:
            self._queues[queue_key] = asyncio.Queue()
            self._workers[queue_key] = asyncio.create_task(self._process_queue(queue_key, topic))

        await self._queues[queue_key].put(payload)

    async def _process_queue(self, queue_key: str, topic: str) -> None:
        q = self._queues[queue_key]
        while True:
            payload = await q.get()
            handlers = list(self._subs.get(topic, []))
            for h in handlers:
                await self._invoke_with_retry(h, payload, topic)

    async def _invoke_with_retry(self, handler: Handler, payload: Dict[str, Any], topic: str) -> None:
        attempts = 0
        backoff_ms = float(self.backoff_base_ms)
        while True:
            attempts += 1
            try:
                with timer("event_handler_ms", {"topic": topic}):
                    await handler(payload)
                inc("event_handler_total", {"topic": topic, "status": "success"})
                return
            except Exception as exc:
                inc("event_handler_total", {"topic": topic, "status": "error"})
                if attempts >= self.max_attempts:
                    _log.error("handler_failed", extra={"topic": topic, "error": str(exc)})
                    await self._send_to_dlq(topic, payload, error=str(exc))
                    return
                await asyncio.sleep(backoff_ms / 1000.0)
                backoff_ms *= float(self.backoff_factor)

    async def _send_to_dlq(self, topic: str, payload: Dict[str, Any], *, error: str) -> None:
        evt = {
            "original_topic": topic,
            "payload": payload,
            "error": error,
            "timestamp": now_ms(),
        }
        self._dlq.append(evt)
        for h in list(self._dlq_handlers):
            try:
                await h(evt)
            except Exception:
                # DLQ-хэндлер не должен падать систему
                pass

    async def close(self) -> None:
        """Останавливает воркеры очередей (используется редко; шина обычно живёт весь процесс)."""
        for t in list(self._workers.values()):
            if not t.done():
                t.cancel()
        await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._queues.clear()
