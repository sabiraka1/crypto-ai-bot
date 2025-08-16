from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Deque, Optional

EventHandler = Callable[[Dict[str, Any]], Awaitable[None]]

@dataclass
class AsyncBus:
    """
    Async pub/sub с per-event backpressure стратегиями и DLQ.
    strategies: {"OrderFilledEvent": "drop_oldest" | "keep_latest" | "block", ...}
    queue_sizes: {"OrderFilledEvent": 1000, ...}
    dlq_max: максимальный размер очереди DLQ (dead-letter).
    """
    strategies: Dict[str, str] = field(default_factory=dict)
    queue_sizes: Dict[str, int] = field(default_factory=dict)
    dlq_max: int = 200

    def __post_init__(self) -> None:
        self._handlers: Dict[str, list[EventHandler]] = {}
        self._queues: Dict[str, asyncio.Queue] = {}
        self._dlq: Deque[Dict[str, Any]] = deque(maxlen=self.dlq_max)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
        if event_type not in self._queues:
            maxsize = int(self.queue_sizes.get(event_type, 1000))
            self._queues[event_type] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, event: Dict[str, Any]) -> None:
        et = str(event.get("type","GenericEvent"))
        q = self._queues.setdefault(et, asyncio.Queue(maxsize=int(self.queue_sizes.get(et, 1000))))
        strat = self.strategies.get(et, "block")
        if strat == "block":
            await q.put(event)
        elif strat == "drop_oldest":
            if q.full():
                try:
                    _ = q.get_nowait()
                    q.task_done()
                except Exception:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._dlq.append({"reason":"queue_full_after_drop","event":event})
        elif strat == "keep_latest":
            if q.full():
                # очищаем всё и оставляем только новый как "последний"
                while not q.empty():
                    try:
                        _ = q.get_nowait(); q.task_done()
                    except Exception:
                        break
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._dlq.append({"reason":"queue_full_keep_latest","event":event})
        else:
            # неизвестная стратегия — отправим в DLQ
            self._dlq.append({"reason":"unknown_strategy","strategy":strat,"event":event})

    async def run_consumer(self, event_type: str) -> None:
        q = self._queues.setdefault(event_type, asyncio.Queue(maxsize=int(self.queue_sizes.get(event_type, 1000))))
        while True:
            ev = await q.get()
            try:
                for h in self._handlers.get(event_type, []):
                    try:
                        await h(ev)
                    except Exception as e:
                        self._dlq.append({"reason":"handler_error","event":ev,"error":type(e).__name__})
            finally:
                q.task_done()

    def dead_letters(self) -> list[Dict[str, Any]]:
        return list(self._dlq)
