# src/crypto_ai_bot/core/events/bus.py
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Set, TypedDict, NotRequired

# -------------------- Типы событий --------------------

class BusEvent(TypedDict, total=False):
    type: str
    ts_ms: int
    symbol: str
    timeframe: str
    payload: NotRequired[Dict[str, Any]]
    error: NotRequired[str]
    key: NotRequired[str]          # для явной сериализации по ключу

class DecisionEvaluatedEvent(BusEvent, total=False):
    type: str                      # "DecisionEvaluated"
    decision: Dict[str, Any]

class OrderExecutedEvent(BusEvent, total=False):
    type: str                      # "OrderExecuted"
    order_id: str
    side: str
    qty: str
    price: float


# -------------------- AsyncEventBus --------------------

Handler = Callable[[BusEvent], Awaitable[None]]

class AsyncEventBus:
    """
    Минимальный асинхронный EventBus:
      - FIFO очередь
      - per-key ordering (по symbol/key)
      - DLQ и репаблиш
      - p95/p99 latency по последним N обработкам
    """

    def __init__(self, *, max_queue: int = 1000, concurrency: int = 4) -> None:
        self._q: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=max_queue)
        self._handlers: Dict[str, List[Handler]] = defaultdict(list)
        self._running: bool = False
        self._tasks: List[asyncio.Task] = []
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)  # per-key lock
        self._dlq: List[Dict[str, Any]] = []
        self._latency_ms: Deque[float] = deque(maxlen=2048)  # кольцевой буфер для pctl
        self._concurrency = max(1, int(concurrency))

    # ---- подписки/публикации ----

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: BusEvent) -> None:
        if "ts_ms" not in event:
            event["ts_ms"] = int(time.time() * 1000)
        await self._q.put(event)

    # ---- управление жизненным циклом ----

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for _ in range(self._concurrency):
            self._tasks.append(asyncio.create_task(self._worker(), name="bus-worker"))

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # мягко завершим: пустим sentinel None через очередь
        for _ in self._tasks:
            await self._q.put({"type": "__stop__"})
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # ---- DLQ / репаблиш ----

    def dlq_size(self) -> int:
        return len(self._dlq)

    async def try_republish_from_dlq(self, limit: int = 50) -> int:
        n = min(limit, len(self._dlq))
        ok = 0
        for _ in range(n):
            item = self._dlq.pop(0)
            ev = item.get("event")
            if ev:
                await self.publish(ev)  # retry
                ok += 1
        return ok

    # ---- диагностика / метрики ----

    def _percentile(self, p: float) -> float:
        # простая pctl по буферу
        if not self._latency_ms:
            return 0.0
        data = sorted(self._latency_ms)
        k = int(round((p / 100.0) * (len(data) - 1)))
        return float(data[max(0, min(k, len(data) - 1))])

    def health(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "queue_size": self._q.qsize(),
            "dlq_size": self.dlq_size(),
            "p95_ms": self._percentile(95.0),
            "p99_ms": self._percentile(99.0),
        }

    # ---- воркеры ----

    async def _worker(self) -> None:
        while True:
            event = await self._q.get()
            if event.get("type") == "__stop__":
                return
            t0 = time.time()
            etype = str(event.get("type") or "")
            # определяем ключ сериализации
            key = str(event.get("key") or event.get("symbol") or "*")
            lock = self._locks[key]
            try:
                async with lock:
                    handlers = list(self._handlers.get(etype, ()))
                    for h in handlers:
                        try:
                            await h(event)
                        except Exception as e:
                            # в DLQ кладём оригинал + ошибка/таймштамп
                            self._dlq.append({"ts_ms": int(time.time() * 1000), "event": dict(event), "error": repr(e), "handler": getattr(h, "__name__", "handler")})
            finally:
                dt_ms = (time.time() - t0) * 1000.0
                self._latency_ms.append(dt_ms)
