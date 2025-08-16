
from __future__ import annotations

import asyncio
import time
from typing import Callable, Awaitable, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.bot import Bot


class Orchestrator:
    """Простой планировщик циклов. По умолчанию сам создаёт Bot,
    а Bot — брокера через фабрику (см. core/bot.py).
    """

    def __init__(self, cfg: Settings, bot: Optional[Bot] = None) -> None:
        self.cfg = cfg
        self.bot = bot or Bot(cfg)
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    def schedule_every(
        self,
        seconds: float,
        fn: Callable[[], Awaitable[None]],
        *,
        jitter: float = 0.1,
    ) -> asyncio.Task:
        async def runner() -> None:
            while not self._stopping:
                t0 = time.perf_counter()
                try:
                    await fn()
                except Exception:  # pragma: no cover
                    # логирование оставляем на уровень utils.logging, если подключён
                    pass
                elapsed = time.perf_counter() - t0
                delay = max(0.0, seconds - elapsed)
                # небольшой джиттер, чтобы петли не совпадали
                if jitter:
                    delay *= 1.0 + jitter * 0.1
                await asyncio.sleep(delay)

        task = asyncio.create_task(runner())
        self._tasks.append(task)
        return task

    async def start(self) -> None:
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
