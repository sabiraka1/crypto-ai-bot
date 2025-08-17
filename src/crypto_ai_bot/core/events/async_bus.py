# src/crypto_ai_bot/core/events/async_bus.py
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional
from collections import deque

from crypto_ai_bot.utils import metrics


EventHandler = Callable[[Any], Awaitable[None]] | Callable[[Any], None]


@dataclass
class _EventCfg:
    strategy: str = "block"   # block | drop_oldest | keep_latest
    maxsize: int = 1000


@dataclass
class _EventPipe:
    queue: asyncio.Queue
    handlers: List[EventHandler]


class AsyncBus:
    """
    Асинхронная шина событий с backpressure per-event и DLQ.
    API:
      - configure_backpressure(event_type, strategy, maxsize)
      - subscribe(event_type, handler)
      - publish(event_type, payload)
      - start()/stop()
    """

    def __init__(self) -> None:
        self._cfg: Dict[str, _EventCfg] = {}
        self._pipes: Dict[str, _EventPipe] = {}
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._dlq = deque(maxlen=1000)  # dead letter queue

    # ---------- config ----------
    def configure_backpressure(self, event_type: str, *, strategy: str = "block", maxsize: int = 1000) -> None:
        self._cfg[event_type] = _EventCfg(strategy=strategy, maxsize=maxsize)

    def _pipe_for(self, event_type: str) -> _EventPipe:
        pipe = self._pipes.get(event_type)
        if pipe is None:
            cfg = self._cfg.get(event_type, _EventCfg())
            q: asyncio.Queue = asyncio.Queue(maxsize=cfg.maxsize)
            pipe = _EventPipe(queue=q, handlers=[])
            self._pipes[event_type] = pipe
            if self._running:
                self._start_consumer(event_type, pipe)
        return pipe

    # ---------- lifecycle ----------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for etype, pipe in self._pipes.items():
            self._start_consumer(etype, pipe)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    def _start_consumer(self, event_type: str, pipe: _EventPipe) -> None:
        async def _runner():
            while self._running:
                try:
                    payload = await pipe.queue.get()
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    self._to_dlq(event_type, {"error": repr(e), "phase": "dequeue"})
                    continue

                for h in list(pipe.handlers):
                    try:
                        if inspect.iscoroutinefunction(h):  # type: ignore
                            await h(payload)               # type: ignore
                        else:
                            # sync → отдельно чтобы не блокировать event loop
                            await asyncio.to_thread(h, payload)  # type: ignore
                        metrics.inc("event_bus_consumed_total", {"event": event_type, "handler": h.__name__})
                    except Exception as e:
                        metrics.inc("event_bus_errors_total", {"event": event_type, "handler": getattr(h, "__name__", "unknown")})
                        self._to_dlq(event_type, {"payload": payload, "error": repr(e), "handler": getattr(h, "__name__", "unknown")})
                pipe.queue.task_done()

        task = asyncio.create_task(_runner(), name=f"bus:{event_type}")
        self._tasks.append(task)

    def _to_dlq(self, event_type: str, item: Any) -> None:
        self._dlq.append({"event": event_type, "item": item})

    # ---------- API ----------
    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        pipe = self._pipe_for(event_type)
        pipe.handlers.append(handler)

    async def publish(self, event_type: str, payload: Any) -> None:
        cfg = self._cfg.get(event_type, _EventCfg())
        pipe = self._pipe_for(event_type)
        q = pipe.queue

        if cfg.strategy == "block":
            await q.put(payload)

        elif cfg.strategy == "drop_oldest":
            if q.full():
                try:
                    _ = q.get_nowait()  # выкидываем старый
                    q.task_done()
                except asyncio.QueueEmpty:
                    pass
            await q.put(payload)

        elif cfg.strategy == "keep_latest":
            # очищаем очередь и кладём только последнюю версию
            while not q.empty():
                try:
                    _ = q.get_nowait()
                    q.task_done()
                except asyncio.QueueEmpty:
                    break
            await q.put(payload)

        else:
            # на всякий случай — как block
            await q.put(payload)

        metrics.inc("event_bus_published_total", {"event": event_type})

    def dlq_snapshot(self, limit: int = 100) -> List[Any]:
        """
        Возвращает последние элементы DLQ, чтобы можно было отдать через /bus/debug.
        """
        return list(self._dlq)[-limit:]
