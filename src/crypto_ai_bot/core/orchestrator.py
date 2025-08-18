# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import random
import time
import logging
from typing import Any, Optional, Dict

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

log = logging.getLogger(__name__)

_GLOBAL_ORCH: Optional["Orchestrator"] = None
def set_global_orchestrator(o: Optional["Orchestrator"]) -> None:  # используется в server.py
    global _GLOBAL_ORCH
    _GLOBAL_ORCH = o


class Orchestrator:
    """
    Периодически триггерит тик (evaluate+optional order) и делает maintenance.
    Добавлен рандомный джиттер и явные логи ошибок вместо «проглатывания».
    """

    def __init__(self, cfg: Any, broker: Any, repos: Any, *, bus: Optional[Any] = None, http: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.broker = broker
        self.repos = repos
        self.bus = bus
        self.http = http

        self._task_tick: Optional[asyncio.Task] = None
        self._task_maint: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._task_tick is None:
            self._task_tick = asyncio.create_task(self._tick_loop(), name="orch.tick")
        if self._task_maint is None:
            self._task_maint = asyncio.create_task(self._maintenance_loop(), name="orch.maintenance")

    async def stop(self) -> None:
        self._stopped.set()
        for t in (self._task_tick, self._task_maint):
            if t:
                t.cancel()
        self._task_tick = None
        self._task_maint = None

    # ---------- loops ----------

    async def _tick_loop(self) -> None:
        sym = getattr(self.cfg, "SYMBOL", "BTC/USDT")
        tf = getattr(self.cfg, "TIMEFRAME", "1h")
        limit = int(getattr(self.cfg, "LIMIT_BARS", 300) or 300)

        base_period = int(getattr(self.cfg, "TICK_PERIOD_SEC", 60) or 60)
        jitter_pct = 0.15  # ±15%

        while not self._stopped.is_set():
            try:
                # Offload sync flow out of event loop (broker is sync)
                import functools
                loop = asyncio.get_running_loop()
                with metrics.timer() as t_flow:
                    fn = functools.partial(
                        uc_eval_and_execute, self.cfg, self.broker, self.repos,
                        symbol=sym, timeframe=tf, limit=limit, bus=self.bus, http=self.http
                    )
                    await loop.run_in_executor(None, fn)
                metrics.observe_histogram("latency_flow_seconds", t_flow.elapsed)
                thr = int(getattr(self.cfg, "PERF_BUDGET_FLOW_P99_MS", 0) or 0)
                if thr > 0 and (t_flow.elapsed * 1000.0) > float(thr):
                    metrics.inc("flow_latency_exceed_total")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("orchestrator_tick_failed: %s", e)
                metrics.inc("orchestrator_tick_errors_total")

            # randomized sleep
            try:
                base = max(1.0, float(base_period))
                jitter = random.uniform(1.0 - jitter_pct, 1.0 + jitter_pct)
                await asyncio.sleep(base * jitter)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("orchestrator_sleep_issue: %s", e)
                await asyncio.sleep(base_period)
    async def _maintenance_loop(self) -> None:
        period = int(getattr(self.cfg, "MAINTENANCE_SEC", 60) or 60)
        while not self._stopped.is_set():
            try:
                self._run_maintenance_once()
                metrics.inc("maintenance_runs_total")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("maintenance_failed: %s", e)
                metrics.inc("maintenance_errors_total")
            try:
                base = max(5.0, float(period))
                jitter = random.uniform(0.9, 1.1)
                await asyncio.sleep(base * jitter)
            except asyncio.CancelledError:
                raise

    # ---------- helpers ----------

    def _run_maintenance_once(self) -> None:
        """
        Безопасные операции обслуживания БД/репозиториев.
        1) Чистим истёкшую идемпотентность (значение — в gauge, не в лейбле).
        2) Можно добавить VACUUM/ANALYZE по расписанию (здесь не трогаем).
        """
        cleaned = 0
        idem = getattr(self.repos, "idempotency", None)
        if idem is not None:
            try:
                # если есть явный метод purge — используем его
                if hasattr(idem, "purge"):
                    cleaned = int(idem.purge()) or 0  # метод сам решит TTL
                else:
                    # на всякий случай — попытка SQL (не уронит, если схемы нет)
                    con = getattr(self.repos, "uow", None)
                    con = getattr(con, "_con", None) or getattr(con, "con", None)
                    if con is not None:
                        cur = con.execute("DELETE FROM idempotency WHERE expires_at IS NOT NULL AND expires_at < strftime('%s','now')")
                        cleaned = int(cur.rowcount or 0)
                        con.commit()
            except Exception as e:
                log.warning("idempotency_purge_failed: %s", e)
                metrics.inc("idempotency_cleanup_errors_total")
        metrics.gauge("idempotency_cleanup_count", float(cleaned))
