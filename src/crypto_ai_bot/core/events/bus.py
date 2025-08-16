from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional


@dataclass
class Event:
    type: str
    payload: Dict[str, Any]


class AsyncBus:
    """
    Async pub/sub со стратегиями backpressure и DLQ.
    backpressure_strategy можно задавать по типу события.
    """

    def __init__(self, max_queue: int = 1000) -> None:
        self.subscribers: Dict[str, List[Callable[[Event], Awaitable[None]]]] = defaultdict(list)
        self.queues: Dict[str, asyncio.Queue[Event]] = defaultdict(lambda: asyncio.Queue(maxsize=max_queue))
        self.backpressure: Dict[str, str] = defaultdict(lambda: "block")  # block|drop_oldest|keep_latest|never_drop
        self.dead_letter_queue: deque[Event] = deque(maxlen=1000)
        self._consumers_started = False

    def set_strategy(self, event_type: str, strategy: str) -> None:
        self.backpressure[event_type] = strategy

    def subscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]) -> None:
        self.subscribers[event_type].append(handler)

    async def _consumer(self, event_type: str) -> None:
        q = self.queues[event_type]
        while True:
            evt = await q.get()
            try:
                handlers = self.subscribers.get(event_type, [])
                for h in handlers:
                    await h(evt)
            except Exception as exc:  # noqa: BLE001
                # в DLQ уходит исходное событие с пометкой ошибки
                self.dead_letter_queue.append(Event(type="DLQ", payload={"orig_type": event_type, "event": evt.payload, "error": str(exc)}))
            finally:
                q.task_done()

    async def start(self) -> None:
        if self._consumers_started:
            return
        self._consumers_started = True
        for etype in list(self.queues.keys()) or ["default"]:
            asyncio.create_task(self._consumer(etype))

    async def publish(self, event: Event) -> None:
        et = event.type
        q = self.queues[et]
        strat = self.backpressure[et]

        try:
            if strat == "block":
                await q.put(event)
            elif strat == "keep_latest":
                while not q.empty():
                    try:
                        q.get_nowait()
                        q.task_done()
                    except Exception:
                        break
                await q.put(event)
            elif strat == "drop_oldest":
                if q.full():
                    try:
                        q.get_nowait()
                        q.task_done()
                    except Exception:
                        pass
                await q.put(event)
            elif strat == "never_drop":
                await q.put(event)  # фактически block
            else:
                await q.put(event)
        except Exception as exc:  # если даже put упал — DLQ
            self.dead_letter_queue.append(Event(type="DLQ", payload={"orig_type": et, "event": event.payload, "error": str(exc)}))
