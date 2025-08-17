from __future__ import annotations

import asyncio
import random
from typing import Callable, Awaitable, List, Optional, Any


class Orchestrator:
    """
    Планировщик фоновых задач бота.
    - Не знает ничего про HTTP, ccxt и т.д.
    - Работает с уже сконструированными зависимостями (cfg, bot, repos).
    """

    def __init__(self, cfg, bot, repos, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.cfg = cfg
        self.bot = bot
        self.repos = repos
        self.loop = loop or asyncio.get_event_loop()

        self._running: bool = False
        self._tasks: List[asyncio.Task] = []

    # ------------- публичный API -------------

    def schedule_every(
        self,
        seconds: float,
        fn: Callable[[], Awaitable[Any]] | Callable[[], Any],
        *,
        jitter: float = 0.1,
        name: Optional[str] = None,
    ) -> None:
        """
        Планирует периодический вызов fn.
        jitter – относительный (0.1 = ±10%).
        """
        async def _runner():
            # небольшой рандом при старте, чтобы не стрелять синхронно
            await asyncio.sleep(random.uniform(0, seconds * jitter))
            while self._running:
                try:
                    res = fn()
                    if asyncio.iscoroutine(res):
                        await res  # type: ignore[func-returns-value]
                except Exception:
                    # никаких падений оркестратора — ошибки уже логируются в самом fn
                    pass
                # следующий запуск
                await asyncio.sleep(seconds * random.uniform(1 - jitter, 1 + jitter))

        task = self.loop.create_task(_runner(), name=name or f"periodic-{getattr(fn, '__name__', 'job')}")
        self._tasks.append(task)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        # ---- обслуживание: периодически обновляем метрики позиций/экспозиции
        # частота берётся из настроек, по умолчанию 30 секунд
        refresh_sec = getattr(self.cfg, "METRICS_REFRESH_SEC", 30)
        if getattr(self.repos, "tracker", None):
            def _update_metrics_safely():
                try:
                    self.repos.tracker.update_metrics()
                except Exception:
                    # намеренно молчим – метрики не должны валить оркестратор
                    pass

            self.schedule_every(refresh_sec, _update_metrics_safely, jitter=0.2, name="positions-metrics")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        # мягкая остановка
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()


# Фабричная функция — удобно вызывать там, где инициализируется бот
def create_default_orchestrator(cfg, bot, repos) -> Orchestrator:
    """
    Конструирует оркестратор и включает обслуживание метрик (если доступен tracker).
    """
    return Orchestrator(cfg=cfg, bot=bot, repos=repos)
