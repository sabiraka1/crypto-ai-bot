# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers import create_broker
from crypto_ai_bot.core.bot import get_bot
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.migrations.runner import apply_all
from crypto_ai_bot.core.storage.repositories import IdempotencyRepositorySQLite
from crypto_ai_bot.utils import metrics


# ────────────────────────────── логгер (без зависимости от utils.logging) ─────
log = logging.getLogger("orchestrator")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


# ─────────────────────────────────── типы ─────────────────────────────────────
PeriodicFn = Callable[[], Awaitable[None]]


@dataclass
class _TaskSpec:
    name: str
    interval_sec: float
    jitter_frac: float
    coro_factory: PeriodicFn
    task: Optional[asyncio.Task] = None


# ───────────────────────────────── Orchestrator ───────────────────────────────
@dataclass
class Orchestrator:
    cfg: Settings
    # следующие поля создаются при старте:
    con: Any = field(default=None, init=False)
    broker: Any = field(default=None, init=False)
    bot: Any = field(default=None, init=False)
    _tasks: List[_TaskSpec] = field(default_factory=list, init=False)
    _stopping: bool = field(default=False, init=False)

    # ─────────────────────────── публичный API ────────────────────────────────

    async def start(self) -> None:
        """
        Стартует инфраструктуру (БД → миграции → брокер → бот), планирует фоновые задачи.
        """
        log.info("Orchestrator starting…")

        # 1) БД (WAL/timeout настраиваются внутри connect() по Settings)
        t0 = time.perf_counter()
        self.con = connect(self.cfg.DB_PATH)  # настроит WAL/busy_timeout согласно нашим правилам
        apply_all(self.con)                   # применяем SQL-версии по порядку
        metrics.inc("db_migrations_applied_total", {})
        metrics.observe("db_startup_seconds", time.perf_counter() - t0, {})

        # 2) брокер (live/paper/backtest) — через фабрику
        self.broker = create_broker(self.cfg)
        metrics.inc("broker_created_total", {"mode": self.cfg.MODE})

        # 3) фасад бота
        self.bot = get_bot(cfg=self.cfg, broker=self.broker, con=self.con)
        metrics.inc("bot_initialized_total", {})

        # 4) планирование фоновых задач
        self._schedule_every(
            seconds=float(self.cfg.SCHEDULE_EVAL_SECONDS),
            name="eval",
            jitter=0.10,
            fn=self._job_eval_and_execute,
        )
        self._schedule_every(
            seconds=float(self.cfg.SCHEDULE_MAINTENANCE_SECONDS),
            name="maintenance",
            jitter=0.10,
            fn=self._job_maintenance,
        )

        # 5) обработчики сигналов (если оркестратор запускается как main)
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.stop()))
        except NotImplementedError:
            # Windows/embedded event loop — сигналов может не быть
            pass

        log.info("Orchestrator started.")

    async def stop(self) -> None:
        """
        Корректно завершает задачи, освобождает ресурсы.
        """
        if self._stopping:
            return
        self._stopping = True
        log.info("Orchestrator stopping…")

        # 1) останавливаем периодические задачи
        for spec in self._tasks:
            if spec.task and not spec.task.done():
                spec.task.cancel()
        # 2) дожидаемся отмены
        for spec in self._tasks:
            if spec.task:
                try:
                    await spec.task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    log.warning("Task %s finished with error on stop: %s", spec.name, e)

        # 3) закрываем соединения (брокер/БД)
        try:
            if hasattr(self.broker, "close"):
                await _maybe_await(self.broker.close())
        except Exception:
            pass

        try:
            if self.con is not None:
                self.con.close()
        except Exception:
            pass

        metrics.inc("orchestrator_stopped_total", {})
        log.info("Orchestrator stopped.")

    def schedule_every(self, seconds: float, fn: PeriodicFn, *, jitter: float = 0.10, name: str = "periodic") -> None:
        """
        Публичный метод для регистрации внешних периодических задач, если нужно.
        """
        self._schedule_every(seconds=seconds, name=name, jitter=jitter, fn=fn)

    # ───────────────────────────── приватные методы ───────────────────────────

    def _schedule_every(self, *, seconds: float, name: str, jitter: float, fn: PeriodicFn) -> None:
        spec = _TaskSpec(name=name, interval_sec=seconds, jitter_frac=jitter, coro_factory=fn)
        spec.task = asyncio.create_task(self._task_runner(spec), name=f"{name}-runner")
        self._tasks.append(spec)
        metrics.inc("orchestrator_task_scheduled_total", {"name": name})

    async def _task_runner(self, spec: _TaskSpec) -> None:
        """
        Бесконечный цикл выполнения задания с интервалом и джиттером.
        """
        try:
            # лёгкий сдвиг старта, чтобы не бить всё одновременно
            await asyncio.sleep(_with_jitter(0.05 * spec.interval_sec, spec.jitter_frac))
            while True:
                t0 = time.perf_counter()
                try:
                    await spec.coro_factory()
                    metrics.inc("orchestrator_task_success_total", {"name": spec.name})
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.exception("Task %s failed: %s", spec.name, e)
                    metrics.inc("orchestrator_task_error_total", {"name": spec.name})
                # спим до следующего запуска
                elapsed = time.perf_counter() - t0
                delay = max(0.0, spec.interval_sec - elapsed)
                await asyncio.sleep(_with_jitter(delay, spec.jitter_frac))
        except asyncio.CancelledError:
            metrics.inc("orchestrator_task_cancelled_total", {"name": spec.name})
            raise

    # ───────────────────────────── периодические задания ──────────────────────

    async def _job_eval_and_execute(self) -> None:
        """
        Основной цикл стратегии: evaluate → (risk) → execute.
        Запускается с интервалом cfg.SCHEDULE_EVAL_SECONDS.
        """
        # cpu-bound/блокирующие вещи делаем в thread, чтобы не блокировать event loop
        def _run():
            return self.bot.eval_and_execute(
                symbol=self.cfg.SYMBOL,
                timeframe=self.cfg.TIMEFRAME,
                limit=self.cfg.FEATURE_LIMIT,
            )

        t0 = time.perf_counter()
        try:
            res = await asyncio.to_thread(_run)
            metrics.observe("pipeline_latency_seconds", time.perf_counter() - t0, {})
            metrics.inc("pipeline_runs_total", {"result": str(res.get('order', {}).get('status', 'unknown'))})
            # опционально — можно логировать краткий срез
            log.debug("eval_and_execute result: %s", _safe_short(res))
        except Exception as e:
            metrics.inc("pipeline_runs_total", {"result": "exception"})
            log.exception("eval_and_execute failed: %s", e)

    async def _job_maintenance(self) -> None:
        """
        Обслуживание:
          - чистка истекших ключей идемпотентности
          - оптимизация SQLite (OPTIMIZE)
        """
        def _maint():
            # 1) чистка идемпотентности
            idem = IdempotencyRepositorySQLite(self.con)
            deleted = idem.purge_expired()
            # 2) оптимизация SQLite (быстрее VACUUM и без полной блокировки)
            cur = self.con.cursor()
            try:
                cur.execute("PRAGMA optimize")
            finally:
                cur.close()
            return deleted

        try:
            deleted = await asyncio.to_thread(_maint)
            metrics.inc("idempotency_purged_total", {"deleted": str(deleted)})
            metrics.inc("db_optimize_total", {})
        except Exception as e:
            log.exception("maintenance failed: %s", e)
            metrics.inc("maintenance_errors_total", {})


# ────────────────────────────── утилиты ───────────────────────────────────────

def _with_jitter(base: float, jitter_frac: float) -> float:
    """
    Возвращает base ± (base * jitter_frac * U[-0.5; 0.5]).
    """
    import random
    if base <= 0 or jitter_frac <= 0:
        return max(0.0, base)
    delta = base * jitter_frac
    return max(0.0, base + random.uniform(-0.5 * delta, 0.5 * delta))


def _safe_short(obj: Dict[str, Any]) -> Dict[str, Any]:
    try:
        d = dict(obj or {})
        # урежем «тяжёлые» поля, если появятся
        for k in ("features", "bars", "ohlcv"):
            if k in d:
                d[k] = "<omitted>"
        return d
    except Exception:
        return {"_nonserializable": True}


# ────────────────────────────── удобный конструктор ───────────────────────────

async def create_and_start(cfg: Optional[Settings] = None) -> Orchestrator:
    """
    Вспомогательная функция: создать оркестратор из Settings.build() и стартовать.
    Удобно для embed-сценариев/скриптов.
    """
    cfg = cfg or Settings.build()
    orch = Orchestrator(cfg=cfg)
    await orch.start()
    return orch
