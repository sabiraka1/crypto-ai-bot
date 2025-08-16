from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, List, Optional

from crypto_ai_bot.core.events.factory import build_bus
from crypto_ai_bot.core.events import EventPriority
from crypto_ai_bot.core.storage.sqlite_adapter import maintenance_maybe_vacuum_analyze

# Type for scheduled async callables (no args)
AsyncNoArg = Callable[[], Awaitable[None]]

class Orchestrator:
    """Lightweight scheduler + event bus lifecycle.
    Правила:
      - НЕ обращается к брокеру напрямую — только bot/public use-cases (внешние тикеры планируются извне).
      - Отвечает за фоновые сервисные задачи (DB maintenance, метрики), и жизненный цикл EventBus.
    """
    def __init__(
        self,
        cfg,
        bot,
        *,
        con=None,
        bus=None,
    ) -> None:
        self.cfg = cfg
        self.bot = bot
        self.con = con
        self.bus = bus or build_bus(cfg)
        self._tasks: List[asyncio.Task] = []
        self._running: bool = False

    # ---------------- Lifecycle ----------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        # 1) start bus
        try:
            await self.bus.start()
        except Exception:
            # не падаем — просто работаем без bus
            self.bus = None

        # 2) планирование обслуживания БД (если есть соединение)
        if self.con is not None and getattr(self.cfg, "DB_MAINTENANCE_ENABLED", True):
            minutes = int(getattr(self.cfg, "DB_MAINTENANCE_INTERVAL_MIN", 30))
            self.schedule_every(
                seconds=max(60, minutes * 60),
                fn=self._db_maintenance_tick,
                jitter=0.2,
            )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # cancel scheduled tasks
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._tasks.clear()

        # stop bus
        if self.bus is not None:
            try:
                await self.bus.stop()
            except Exception:
                pass

    # ---------------- Scheduling API ----------------
    def schedule_every(self, *, seconds: int, fn: AsyncNoArg, jitter: float = 0.1) -> None:
        """Запустить периодическую асинхронную задачу.
        seconds — базовый интервал;
        jitter — случайный разброс (0..jitter) для уменьшения синхронности.
        fn — асинхронная функция без аргументов.
        """
        async def _runner():
            while self._running:
                try:
                    await fn()
                except Exception as e:
                    # публикуем ошибку в bus как метрику/аудит
                    if self.bus is not None:
                        try:
                            await self.bus.publish(
                                {"type": "audit.scheduler_error", "detail": str(e)},
                                priority=EventPriority.HIGH,
                            )
                        except Exception:
                            pass
                # sleep with jitter
                base = float(seconds)
                # 0..jitter * base
                delta = random.random() * (jitter * base)
                await asyncio.sleep(base + delta)

        task = asyncio.create_task(_runner())
        self._tasks.append(task)

    # ---------------- Maintenance tasks ----------------
    async def _db_maintenance_tick(self) -> None:
        """Периодический сервис: ANALYZE/VACUUM по эвристикам.

        Ничего не ломает и не блокирует торговлю. Отчёт уходит в bus (metrics.db_maintenance).
        Пороги читаются из cfg при наличии, иначе используются дефолты.
        """
        if self.con is None:
            return
        try:
            res = maintenance_maybe_vacuum_analyze(
                self.con,
                max_fragmentation_pct=float(getattr(self.cfg, "DB_VACUUM_MAX_FRAGMENTATION", 0.15)),
                min_vacuum_bytes=int(getattr(self.cfg, "DB_VACUUM_MIN_SIZE_BYTES", 50 * 1024 * 1024)),
                min_hours_between_vacuum=int(getattr(self.cfg, "DB_VACUUM_MIN_HOURS", 12)),
                min_hours_between_analyze=int(getattr(self.cfg, "DB_ANALYZE_MIN_HOURS", 6)),
            )
        except Exception as e:
            if self.bus is not None:
                try:
                    await self.bus.publish(
                        {"type": "metrics.db_maintenance", "status": "error", "detail": str(e)},
                        priority=EventPriority.NORMAL,
                    )
                except Exception:
                    pass
            return

        if self.bus is not None:
            try:
                await self.bus.publish(
                    {"type": "metrics.db_maintenance", "status": "ok", **res},
                    priority=EventPriority.LOW,
                )
            except Exception:
                pass
