# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Callable, Optional, Any, Dict, List

from .settings import Settings
from .brokers import create_broker, ExchangeInterface
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.storage.sqlite_adapter import schedule_maintenance


@dataclass
class _Job:
    interval_seconds: int
    fn: Callable[[], Any]                 # sync-функция (выполним в to_thread)
    jitter_frac: float = 0.1              # 0..1 — доля интервала, разброс ±jitter*interval
    name: str = "job"


class Orchestrator:
    """
    Лёгкий планировщик периодических задач для бота:
      - schedule_every(seconds, fn, jitter=0.1): регистрирует джоб;
      - start()/stop(): запуск/останов всех фоновых задач;
      - встроено: плановое обслуживание SQLite (VACUUM/ANALYZE/статистика/очистка идемпотентности).
    Правила:
      - никаких блокировок event-loop: все Джобы исполняются через asyncio.to_thread();
      - метрики: scheduler_job_runs_total / scheduler_job_fail_total / scheduler_job_seconds;
      - безопасный shutdown (Cancel-aware).
    """

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        # Брокер создаётся здесь, но оркестратор НЕ должен вызывать его напрямую — только передавать в higher-level циклы.
        self.broker: ExchangeInterface = create_broker(cfg)

        self._jobs: List[_Job] = []
        self._tasks: List[asyncio.Task] = []
        self._running: bool = False

        # --- ВСТРОЕННОЕ ОБСЛУЖИВАНИЕ БД ---
        # Подключаем периодическое обслуживание SQLite: каждые 6ч, с очисткой протухших ключей идемпотентности.
        # Можно переопределить периодика через ENV (DB_MAINT_EVERY_HOURS).
        every_hours = float(getattr(self.cfg, "DB_MAINT_EVERY_HOURS", 6.0))
        schedule_maintenance(
            self,
            db_path=getattr(self.cfg, "DB_PATH", "data/bot.sqlite3"),
            every_hours=every_hours,
            purge_idempotency=True,
            idem_ttl_seconds=int(getattr(self.cfg, "IDEMPOTENCY_TTL_SECONDS", 3600)),
        )

    # ------------------------------------------------------------------ #
    #                  API планировщика для других модулей               #
    # ------------------------------------------------------------------ #

    def schedule_every(self, seconds: int, fn: Callable[[], Any], *, jitter: float = 0.1, name: str = "job") -> None:
        """
        Регистрирует периодическую задачу.
        - seconds: базовый интервал (>= 1 сек)
        - jitter: доля интервала 0..1; реальная пауза = seconds ± random*jitter*seconds
        - fn: синхронная функция без аргументов (будет исполнена в рабочем треде)
        """
        sec = max(1, int(seconds))
        jit = float(min(max(jitter, 0.0), 1.0))
        self._jobs.append(_Job(interval_seconds=sec, fn=fn, jitter_frac=jit, name=name))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # стартуем отдельную задачу под каждый зарегистрированный джоб
        for job in self._jobs:
            self._tasks.append(asyncio.create_task(self._runner(job)))
        metrics.inc("scheduler_started_total", {"jobs": str(len(self._jobs))})

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # корректно отменяем все таски
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        metrics.inc("scheduler_stopped_total", {})

    # ------------------------------------------------------------------ #
    #                           Внутренняя логика                        #
    # ------------------------------------------------------------------ #

    async def _runner(self, job: _Job) -> None:
        """
        Вечный цикл исполнения одного джоба:
          1) sleep interval ± jitter
          2) выполнить fn в рабочем треде
          3) метрики, защита от исключений, продолжение цикла
        """
        # Небольшой рандомный стартовый сдвиг, чтобы «размазать» нагрузку
        await asyncio.sleep(random.uniform(0.0, min(1.0, job.jitter_frac)) * job.interval_seconds)

        while self._running:
            # Расчёт следующей паузы с jitter
            jitter_span = job.jitter_frac * job.interval_seconds
            sleep_for = job.interval_seconds + random.uniform(-jitter_span, jitter_span)
            sleep_for = max(1.0, sleep_for)
            try:
                await asyncio.sleep(sleep_for)
                t0 = time.perf_counter()
                # Исполняем синхронный джоб в треде, чтобы не блокировать event-loop
                res = await asyncio.to_thread(job.fn)
                metrics.inc("scheduler_job_runs_total", {"job": job.name})
                metrics.observe("scheduler_job_seconds", time.perf_counter() - t0, {"job": job.name, "result": "ok"})
            except asyncio.CancelledError:
                # корректный выход
                break
            except Exception as e:
                metrics.inc("scheduler_job_fail_total", {"job": job.name})
                metrics.observe("scheduler_job_seconds", 0.0, {"job": job.name, "result": "err"})

    # ------------------------------------------------------------------ #
    #         Пример: подключение твоих торговых циклов (опционально)    #
    # ------------------------------------------------------------------ #

    def schedule_trading_loop(self, fn: Callable[[], Any], *, every_seconds: int = 30) -> None:
        """
        Удобная обёртка: регистрирует твой торговый цикл (evaluate → risk → place_order)
        как периодическую задачу. Передай сюда уже собранную функцию без аргументов.
        """
        self.schedule_every(every_seconds, fn, jitter=0.1, name="trading-loop")
