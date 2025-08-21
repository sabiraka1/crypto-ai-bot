from __future__ import annotations

"""
Простая асинхронная шина событий (in-memory), без внешних зависимостей.
Совместима с ранее упоминавшимся AsyncEventBus: start/stop/publish/subscribe/qsize.
"""

import asyncio
from collections import defaultdict
from typing import Awaitable, Callable, Dict, List, Any, Coroutine, Optional


Handler = Callable[[str, dict], Awaitable[None]]


class AsyncEventBus:
    def __init__(self, max_queue: int = 2048, concurrency: int = 4) -> None:
        self._q: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=max_queue)
        self._subs: Dict[str, List[Handler]] = defaultdict(list)
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._concurrency = concurrency

    def qsize(self) -> int:
        return self._q.qsize()

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, payload: dict) -> None:
        await self._q.put((topic, payload))

    async def _worker(self) -> None:
        while self._running:
            try:
                topic, payload = await self._q.get()
                for h in self._subs.get(topic, []):
                    try:
                        await h(topic, payload)
                    except Exception:
                        # здесь можно инкрементить метрику ошибок
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._workers = [asyncio.create_task(self._worker(), name=f"bus-{i}") for i in range(self._concurrency)]

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
