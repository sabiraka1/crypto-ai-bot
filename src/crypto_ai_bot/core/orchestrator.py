# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations
import asyncio
import random
from typing import Any

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute

class Orchestrator:
    def __init__(self, cfg: Any, broker: Any, repos: Any, bus: Any, http: Any) -> None:
        self.cfg = cfg
        self.broker = broker
        self.repos = repos
        self.bus = bus
        self.http = http
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def _tick_loop(self) -> None:
        sym = self.cfg.symbol
        tf = self.cfg.timeframe
        limit = int(self.cfg.limit_bars)

        base_period = int(getattr(self.cfg, "tick_period_sec", 60) or 60)

        while not self._stopped.is_set():
            try:
                loop = asyncio.get_running_loop()
                with metrics.timer() as t_flow:
                    await loop.run_in_executor(
                        None,
                        lambda: eval_and_execute(self.cfg, self.broker, self.repos,
                                                symbol=sym, timeframe=tf, limit=limit,
                                                bus=self.bus, http=self.http)
                    )
                metrics.observe_histogram("latency_flow_seconds", t_flow.elapsed)
                thr_ms = int(getattr(self.cfg, "perf_budget_flow_p99_ms", 0) or 0)
                if thr_ms > 0 and (t_flow.elapsed * 1000.0) > float(thr_ms):
                    metrics.inc("flow_latency_exceed_total")
            except asyncio.CancelledError:
                raise
            except Exception:
                metrics.inc("orchestrator_tick_errors_total")
            # jitter sleep
            try:
                jitter = random.uniform(0.85, 1.15)
                await asyncio.sleep(max(1.0, float(base_period)) * jitter)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(float(base_period))

    async def start(self):
        if self._task is None or self._task.done():
            self._stopped.clear()
            self._task = asyncio.create_task(self._tick_loop(), name="orchestrator")

    async def stop(self):
        self._stopped.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=1.5)
            except Exception:
                self._task.cancel()
