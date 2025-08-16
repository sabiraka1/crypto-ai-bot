from __future__ import annotations

import asyncio
import random
from typing import Callable, Awaitable, Optional

from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.bot import TradingBot
from crypto_ai_bot.utils import metrics

class Orchestrator:
    def __init__(self, cfg, *, broker=None, **repos) -> None:
        self.cfg = cfg
        self.broker = broker or create_broker(cfg)
        self.bot = TradingBot(cfg, self.broker, **repos)
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # плановая задача: основной тикер
        interval = float(getattr(self.cfg, "SCHEDULE_INTERVAL_S", 60.0))
        self.schedule_every(interval, self._tick_once, jitter=0.1)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def schedule_every(self, seconds: float, fn: Callable[[], Awaitable[None]], *, jitter: float = 0.1) -> None:
        async def _runner():
            while self._running:
                try:
                    await fn()
                except Exception as e:
                    metrics.inc("orchestrator_errors_total", {"type": type(e).__name__})
                # sleep with jitter
                j = random.uniform(-jitter, jitter)
                await asyncio.sleep(max(0.0, seconds * (1.0 + j)))
        task = asyncio.create_task(_runner())
        self._tasks.append(task)

    async def _tick_once(self) -> None:
        res = self.bot.eval_and_execute()
        # простая метрика по действию
        act = (res.get("decision") or {}).get("action") if isinstance(res, dict) else None
        if act:
            metrics.inc("orchestrator_actions_total", {"action": str(act)})
