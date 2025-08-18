from __future__ import annotations
import asyncio
from typing import Any
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute

class Orchestrator:
    def __init__(self, settings, broker, bus):
        self.settings = settings
        self.broker = broker
        self.bus = bus
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _tick(self):
        """Один цикл: offload тяжелую синхронную логику в threadpool,
        чтобы не блокировать event loop (сетевые вызовы/брокер синхронный)."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, eval_and_execute, self.settings, self.broker, self.bus)

    async def _run(self):
        interval = float(getattr(self.settings, "TICK_INTERVAL_SEC", 5.0))
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                # ошибки не валим, у вас есть DLQ в bus/метрики
                pass
            await asyncio.sleep(interval)

    async def start(self):
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="orchestrator")

    async def stop(self):
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=1.5)
            except Exception:
                self._task.cancel()
