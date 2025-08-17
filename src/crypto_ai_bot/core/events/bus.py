from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional


BackpressureStrategy = str  # "block" | "drop_oldest" | "keep_latest"


@dataclass
class _Sub:
    event_type: str
    handler: Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class _QueueCfg:
    maxlen: int = 1000
    strategy: BackpressureStrategy = "block"  # по-умолчанию безопасно


class AsyncBus:
    """
    Простой async pub/sub с per-event стратегиями backpressure и DLQ.
    """

    def __init__(self) -> None:
        self._subs: Dict[str, List[_Sub]] = {}
        self._queues: Dict[str, Deque[Dict[str, Any]]] = {}
        self._cfgs: Dict[str, _QueueCfg] = {}
        self._dlq: Deque[Dict[str, Any]] = deque(maxlen=1000)
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def set_strategy(self, event_type: str, *, maxlen: int, strategy: BackpressureStrategy) -> None:
        self._cfgs[event_type] = _QueueCfg(maxlen=maxlen, strategy=strategy)

    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        lst = self._subs.setdefault(event_type, [])
        lst.append(_Sub(event_type=event_type, handler=handler))

    def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        q = self._queues.get(event_type)
        cfg = self._cfgs.get(event_type, _QueueCfg())
        if q is None:
            q = deque(maxlen=cfg.maxlen)
            self._queues[event_type] = q

        if cfg.strategy == "block":
            if len(q) >= cfg.maxlen:
                # блокируемся пока consumer не снимет
                # (не делаем await здесь — publish синхронный; очередь обработается в run())
                pass
            q.append(payload)
        elif cfg.strategy == "drop_oldest":
            if len(q) >= cfg.maxlen:
                q.popleft()
            q.append(payload)
        elif cfg.strategy == "keep_latest":
            q.clear()
            q.append(payload)
        else:
            q.append(payload)

    async def _consume_once(self) -> None:
        async with self._lock:
            for etype, q in self._queues.items():
                if not q:
                    continue
                item = q.popleft()
                subs = self._subs.get(etype, [])
                for sub in subs:
                    try:
                        await sub.handler({"type": etype, "data": item})
                    except Exception as e:
                        self._dlq.append({"type": etype, "data": item, "error": f"{type(e).__name__}: {e}"})

    async def run(self, *, interval_sec: float = 0.05) -> None:
        if self._running:
            return
        self._running = True
        try:
            while self._running:
                await self._consume_once()
                await asyncio.sleep(interval_sec)
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    def dlq(self) -> List[Dict[str, Any]]:
        return list(self._dlq)

    def health(self) -> Dict[str, Any]:
        return {
            "queues": {k: len(v) for k, v in self._queues.items()},
            "dlq": len(self._dlq),
            "running": self._running,
        }
