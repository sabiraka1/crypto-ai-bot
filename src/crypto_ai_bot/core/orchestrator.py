# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

_HIST_BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000)

def _observe_hist(name: str, value_ms: int, labels: Optional[dict] = None) -> None:
    labels = dict(labels or {})
    for b in _HIST_BUCKETS_MS:
        if value_ms <= b:
            metrics.inc(f"{name}_bucket", {**labels, "le": str(b)})
    metrics.inc(f"{name}_bucket", {**labels, "le": "+Inf"})
    metrics.observe(f"{name}_sum", value_ms, labels)
    metrics.inc(f"{name}_count", labels)


class Orchestrator:
    def __init__(self, cfg: Settings, broker: Any, repos: Any, bus: Any | None = None) -> None:
        self.cfg = cfg
        self.broker = broker
        self.repos = repos
        self.bus = bus
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def schedule_every(self, seconds: int, fn: Callable, *, jitter: float = 0.1) -> None:
        async def runner():
            # простой фон
            while self._running:
                t0 = time.perf_counter()
                try:
                    await asyncio.to_thread(fn)
                except Exception:
                    pass
                dt = int((time.perf_counter() - t0) * 1000)
                _observe_hist("orchestrator_tick_ms", dt, {"mode": self.cfg.MODE})
                # джиттер
                await asyncio.sleep(max(0.0, seconds + (jitter * seconds)))

        self._tasks.append(asyncio.create_task(runner()))

    async def start(self) -> None:
        self._running = True

        symbol = self.cfg.SYMBOL
        timeframe = self.cfg.TIMEFRAME
        limit = int(getattr(self.cfg, "LIMIT_BARS", 300))

        def _tick():
            if getattr(self.cfg, "ENABLE_TRADING", False):
                uc_eval_and_execute(self.cfg, self.broker, self.repos, symbol=symbol, timeframe=timeframe, limit=limit, bus=self.bus)
            else:
                uc_evaluate(self.cfg, self.broker, symbol=symbol, timeframe=timeframe, limit=limit, bus=self.bus)

        period = int(getattr(self.cfg, "TICK_PERIOD_SEC", 60))
        self.schedule_every(period, _tick)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
