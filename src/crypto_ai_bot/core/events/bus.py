from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from enum import IntEnum

try:
    from crypto_ai_bot.utils import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *a, **k): pass
        def observe(self, *a, **k): pass
        def export(self): return ""
    metrics = _Dummy()  # type: ignore

Handler = Callable[[dict], Awaitable[None]] | Callable[[dict], None]

class EventPriority(IntEnum):
    HIGH = 0
    NORMAL = 1
    LOW = 2

# Default strategy if no match
DEFAULT_BACKPRESSURE = "block"

def _match_strategy(overrides: Dict[str, str], event_type: str) -> str:
    """Longest-prefix '*' matcher.
    Exact match wins. Then prefix like 'orders.*' wins (longest).
    Fallback to DEFAULT_BACKPRESSURE.
    """
    if event_type in overrides:
        return overrides[event_type]
    best_len = -1
    best = None
    for pat, strat in overrides.items():
        if pat.endswith('*'):
            pref = pat[:-1]
            if event_type.startswith(pref) and len(pref) > best_len:
                best = strat
                best_len = len(pref)
    return best or DEFAULT_BACKPRESSURE

class AsyncBus:
    """Async in-proc event bus with per-type backpressure strategies and priorities.
    API:
      subscribe(event_type, handler)
      publish(event: dict, *, priority=EventPriority.NORMAL)
      start(); stop()
      health() -> dict

    Notes:
      - event MUST contain 'type' (str)
      - handlers can be sync or async; sync handlers run in the loop's default executor
    """
    def __init__(
        self,
        *,
        max_queue: int = 1000,
        backpressure_overrides: Optional[Dict[str, str]] = None,
    ) -> None:
        self._queue: asyncio.PriorityQueue[Tuple[int, int, dict]] = asyncio.PriorityQueue(max_queue)
        self._subs: Dict[str, List[Handler]] = {}
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._drops_total: int = 0
        self._drops_latest: int = 0
        self._drops_oldest: int = 0
        self._seq: int = 0  # tie-breaker to preserve FIFO inside same priority
        self._overrides = backpressure_overrides or {}

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subs.setdefault(event_type, []).append(handler)

    async def publish(self, event: dict, *, priority: EventPriority = EventPriority.NORMAL) -> None:
        et = str(event.get("type") or "*")
        strat = _match_strategy(self._overrides, et)
        item = (int(priority), self._seq, event)
        self._seq += 1
        if not self._queue.full():
            await self._queue.put(item)
            return
        # queue is full
        if strat == "block":
            await self._queue.put(item)  # apply backpressure to publisher
            return
        if strat == "drop_oldest":
            try:
                _ = self._queue.get_nowait()  # drop one (oldest within current priority ordering)
                self._queue.task_done()
                self._drops_total += 1
                self._drops_oldest += 1
                try:
                    metrics.inc("bus_drop_total", {"strategy": "drop_oldest", "type": et})
                except Exception:
                    pass
            except asyncio.QueueEmpty:
                pass
            await self._queue.put(item)
            return
        if strat == "keep_latest":
            # we keep backlog; drop the new one
            self._drops_total += 1
            self._drops_latest += 1
            try:
                metrics.inc("bus_drop_total", {"strategy": "keep_latest", "type": et})
            except Exception:
                pass
            return
        # default
        await self._queue.put(item)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            prio, _, event = await self._queue.get()
            et = str(event.get("type") or "*")
            handlers = (self._subs.get(et) or []) + (self._subs.get("*") or [])
            for h in handlers:
                try:
                    if asyncio.iscoroutinefunction(h):  # type: ignore[arg-type]
                        await h(event)  # type: ignore[misc]
                    else:
                        await loop.run_in_executor(None, h, event)  # type: ignore[misc]
                except Exception:  # pragma: no cover
                    try:
                        metrics.inc("bus_handler_errors_total", {"type": et})
                    except Exception:
                        pass
            self._queue.task_done()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def health(self) -> dict:
        return {
            "queue_size": self._queue.qsize(),
            "drops_total": self._drops_total,
            "drops_latest": self._drops_latest,
            "drops_oldest": self._drops_oldest,
            "subs": {k: len(v) for k, v in self._subs.items()},
            "overrides": dict(self._overrides),
        }
