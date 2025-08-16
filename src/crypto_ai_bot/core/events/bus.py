from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List

from crypto_ai_bot.utils.metrics import inc, set_gauge


@dataclass
class Event:
    type: str
    payload: Dict[str, Any]


_DEFAULT_STRATEGY_BY_EVENT = {
    "OrderFilledEvent": "never_drop",
    "PriceUpdateEvent": "keep_latest",
    "MetricEvent": "drop_oldest",
}


class AsyncBus:
    """
    Async pub/sub с per-event backpressure и DLQ.
    """
    def __init__(self, max_queue: int = 1000) -> None:
        self.subscribers: Dict[str, List[Callable[[Event], Awaitable[None]]]] = defaultdict(list)
        self.queues: Dict[str, asyncio.Queue[Event]] = defaultdict(lambda: asyncio.Queue(maxsize=max_queue))
        self.backpressure: Dict[str, str] = defaultdict(lambda: "block")
        self.dead_letter_queue: deque[Event] = deque(maxlen=1000)
        self._consumers_started = False

        for etype, strat in _DEFAULT_STRATEGY_BY_EVENT.items():
            self.backpressure[etype] = strat

    def set_strategy(self, event_type: str, strategy: str) -> None:
        self.backpressure[event_type] = strategy

    def subscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]) -> None:
        self.subscribers[event_type].append(handler)

    async def _consumer(self, event_type: str) -> None:
        q = self.queues[event_type]
        while True:
            evt = await q.get()
            try:
                for h in self.subscribers.get(event_type, []):
                    await h(evt)
            except Exception as exc:  # noqa: BLE001
                self.dead_letter_queue.append(Event(type="DLQ", payload={
                    "orig_type": event_type, "event": evt.payload, "error": str(exc)
                }))
                set_gauge("dlq_depth", float(len(self.dead_letter_queue)))
            finally:
                q.task_done()

    async def start(self) -> None:
        if self._consumers_started:
            return
        self._consumers_started = True
        asyncio.create_task(self._consumer("default"))

    async def publish(self, event: Event) -> None:
        et = event.type
        q = self.queues[et]
        strat = self.backpressure[et]

        try:
            if strat == "block":
                await q.put(event)

            elif strat == "keep_latest":
                drops = 0
                while not q.empty():
                    try:
                        q.get_nowait()
                        q.task_done()
                        drops += 1
                    except Exception:
                        break
                if drops:
                    inc("events_dropped_total", {"strategy": strat, "type": et}, drops)
                await q.put(event)

            elif strat == "drop_oldest":
                if q.full():
                    try:
                        q.get_nowait()
                        q.task_done()
                        inc("events_dropped_total", {"strategy": strat, "type": et}, 1.0)
                    except Exception:
                        pass
                await q.put(event)

            elif strat == "never_drop":
                await q.put(event)

            else:
                await q.put(event)
        except Exception as exc:
            self.dead_letter_queue.append(Event(type="DLQ", payload={
                "orig_type": et, "event": event.payload, "error": str(exc)
            }))
            set_gauge("dlq_depth", float(len(self.dead_letter_queue)))

    # ---- диагностика
    def stats(self) -> dict:
        out = {"events": {}, "dlq_depth": len(self.dead_letter_queue)}
        for et, q in self.queues.items():
            out["events"][et] = {
                "size": q.qsize(),
                "max": q.maxsize,
                "strategy": self.backpressure.get(et, "block"),
                "subscribers": len(self.subscribers.get(et, [])),
            }
        return out
