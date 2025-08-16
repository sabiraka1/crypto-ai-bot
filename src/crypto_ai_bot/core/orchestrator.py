# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict

from crypto_ai_bot.utils import metrics, time_sync as ts


class Orchestrator:
    """Простой планировщик фоновых задач + обслуживание (идемпотентность, time_sync).
    Не трогает конкретные реализации — всё передаётся в конструктор.
    """

    def __init__(self, *, cfg: Any, broker: Any, repos: Dict[str, Any], http) -> None:
        self._cfg = cfg
        self._broker = broker
        self._repos = repos
        self._http = http
        self._tasks: set[asyncio.Task] = set()
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # расписания
        self.schedule_every(5, self._tick_safe)  # пример: 5сек для демо
        self.schedule_every(60, self._maintenance_safe)

    async def stop(self) -> None:
        self._running = False
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def schedule_every(self, seconds: int, fn: Callable[[], Awaitable[None]], *, jitter: float = 0.1) -> None:
        async def _runner():
            try:
                while self._running:
                    t0 = time.perf_counter()
                    try:
                        await fn()
                    except Exception:
                        pass
                    dt = time.perf_counter() - t0
                    await asyncio.sleep(max(0.0, seconds - dt))
            except asyncio.CancelledError:
                return
        task = asyncio.create_task(_runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ───────────── внутренние задания ─────────────

    async def _tick_safe(self) -> None:
        # здесь можно вызвать UC eval_and_execute по расписанию, но в проде мы дергаем /tick
        metrics.inc("orch_tick_total")

    async def _maintenance_safe(self) -> None:
        try:
            # чистка идемпотентности
            idr = self._repos.get("idempotency")
            if idr and hasattr(idr, "purge_expired"):
                purged = idr.purge_expired()
                metrics.inc("idempotency_purged_total", {"count": str(purged)})

            # обновление кэша смещения времени
            ts.ensure_recent_measurement(self._http, max_age_sec=60)
        except Exception:
            metrics.inc("orch_maintenance_errors_total")
