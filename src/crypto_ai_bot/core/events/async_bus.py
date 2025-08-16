# src/crypto_ai_bot/core/events/async_bus.py
from __future__ import annotations

import asyncio
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, Dict, List, Literal, Optional, Tuple

from crypto_ai_bot.utils import metrics

AHandler = Callable[[Any], Awaitable[None]]
BackpressurePolicy = Literal["block", "drop_oldest", "keep_latest"]


def _event_type_of(event: Any) -> str:
    if isinstance(event, dict):
        et = event.get("type") or event.get("event_type")
        if not et:
            raise ValueError("event dict must contain 'type' or 'event_type'")
        return str(et)
    for attr in ("event_type", "type", "__class__.__name__"):
        if hasattr(event, attr):
            val = getattr(event, attr)
            if isinstance(val, str):
                return val
    return event.__class__.__name__


@dataclass
class _Stats:
    enqueued_total: int = 0
    delivered_total: int = 0
    dropped_total: int = 0
    handler_errors_total: int = 0


class AsyncBus:
    """
    Асинхронная pub/sub шина:
      - publish(event): складывает события в очередь.
      - Параллелизм контролируется числом воркеров.
      - Backpressure: 'block' | 'drop_oldest' | 'keep_latest'.
      - DLQ содержит события с ошибками хэндлеров.
    """

    def __init__(
        self,
        *,
        max_queue_size: int = 1000,
        workers: int = 1,
        backpressure: BackpressurePolicy = "drop_oldest",
        dlq_max: int = 1000,
        name: str = "async-bus",
    ) -> None:
        assert workers >= 1
        self._name = name
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max(1, max_queue_size))
        self._subs: Dict[str, List[AHandler]] = defaultdict(list)
        self._subs_all: List[AHandler] = []
        self._dlq: Deque[Tuple[str, Any, str]] = deque(maxlen=max(1, dlq_max))
        self._stats = _Stats()
        self._workers_n = int(workers)
        self._backpressure = backpressure
        self._tasks: List[asyncio.Task] = []
        self._stopped = asyncio.Event()

    # ---------------- подписки ----------------

    def subscribe(self, event_type: str, handler: AHandler) -> None:
        if event_type == "*":
            self._subs_all.append(handler)
        else:
            self._subs[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: AHandler) -> None:
        try:
            if event_type == "*":
                self._subs_all.remove(handler)
            else:
                self._subs[event_type].remove(handler)
        except ValueError:
            pass

    # ---------------- запуск/останов ----------------

    async def start(self) -> None:
        if self._tasks:
            return
        self._stopped.clear()
        for i in range(self._workers_n):
            self._tasks.append(asyncio.create_task(self._worker(i)))
        metrics.inc("events_bus_starts_total", {"bus": self._name})

    async def stop(self) -> None:
        self._stopped.set()
        for _ in self._tasks:
            await self._queue.put(None)  # сигнал остановки для каждого воркера
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        metrics.inc("events_bus_stops_total", {"bus": self._name})

    # ---------------- публикация ----------------

    async def publish(self, event: Any) -> None:
        et = _event_type_of(event)
        # backpressure
        put_ok = False
        if self._backpressure == "block":
            await self._queue.put(event)
            put_ok = True
        else:
            try:
                self._queue.put_nowait(event)
                put_ok = True
            except asyncio.QueueFull:
                if self._backpressure == "drop_oldest":
                    try:
                        _ = self._queue.get_nowait()  # удалить самый старый
                        self._queue.task_done()
                    except asyncio.QueueEmpty:
                        pass
                    # пробуем снова
                    try:
                        self._queue.put_nowait(event)
                        put_ok = True
                    except asyncio.QueueFull:
                        put_ok = False
                elif self._backpressure == "keep_latest":
                    # просто не кладём новое событие
                    put_ok = False

        if put_ok:
            self._stats.enqueued_total += 1
            metrics.inc("events_enqueued_total", {"type": et, "bus": self._name})
        else:
            self._stats.dropped_total += 1
            metrics.inc("events_dropped_total", {"type": et, "bus": self._name, "policy": self._backpressure})

        # обновим метрику длины очереди (в режиме observe)
        metrics.observe("events_queue_length", float(self._queue.qsize()), {"bus": self._name})

    # ---------------- воркер ----------------

    async def _worker(self, idx: int) -> None:
        while not self._stopped.is_set():
            evt = await self._queue.get()
            if evt is None:  # сигнал остановки
                self._queue.task_done()
                break

            et = _event_type_of(evt)
            handlers = list(self._subs.get(et, ())) + list(self._subs_all)
            t0 = time.perf_counter()
            if not handlers:
                self._stats.delivered_total += 1
                self._queue.task_done()
                metrics.observe("events_dispatch_seconds", time.perf_counter() - t0, {"type": et, "bus": self._name})
                continue

            for h in handlers:
                try:
                    await h(evt)
                except Exception as e:
                    self._stats.handler_errors_total += 1
                    tb = traceback.format_exc(limit=3)
                    self._dlq.append((et, evt, f"{type(e).__name__}: {e}\n{tb}"))
                    metrics.inc("events_handler_errors_total", {"type": et, "bus": self._name})
            self._stats.delivered_total += 1
            self._queue.task_done()
            metrics.observe("events_dispatch_seconds", time.perf_counter() - t0, {"type": et, "bus": self._name})
            metrics.observe("events_dlq_size", float(len(self._dlq)), {"bus": self._name})

    # ---------------- DLQ / health ----------------

    def dlq_dump(self, limit: int = 50) -> list[dict]:
        items = list(self._dlq)[-limit:]
        out: List[Dict[str, Any]] = []
        for et, ev, err in items:
            out.append({"type": et, "event": ev, "error": err})
        return out

    def health(self) -> Dict[str, Any]:
        st = {
            "queue_size": self._queue.qsize(),
            "enqueued_total": self._stats.enqueued_total,
            "delivered_total": self._stats.delivered_total,
            "dropped_total": self._stats.dropped_total,
            "handler_errors_total": self._stats.handler_errors_total,
            "dlq_size": len(self._dlq),
            "policy": self._backpressure,
            "workers": self._workers_n,
            "status": "healthy" if len(self._dlq) == 0 else "degraded",
        }
        return st
