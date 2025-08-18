# src/crypto_ai_bot/app/tasks/reconciler.py
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("tasks.reconciler")


class Reconciler:
    """
    Периодический тикер защитных выходов + локальная чистка идемпотентности.
    Никаких внешних импортов из проекта — зависимости приходят в конструктор.
    """

    def __init__(
        self,
        *,
        cfg: Any,
        protective_exits: Optional[Any] = None,
        idempotency_repo: Optional[Any] = None,
        interval_s: float = 60.0,
    ) -> None:
        self._cfg = cfg
        self._exits = protective_exits
        self._idem = idempotency_repo
        self._interval_s = max(0.05, float(interval_s))
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self.run(), name="reconciler")

    def stop(self) -> None:
        self._stop.set()

    async def join(self) -> None:
        t = self._task
        if t:
            try:
                await t
            finally:
                self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                # 1) защитные выходы
                if self._exits is not None and hasattr(self._exits, "tick"):
                    try:
                        self._exits.tick()
                    except Exception as e:
                        # <— РАНЬШЕ ЭТО ТЕРЯЛОСЬ, ТЕПЕРЬ ЛОГИРУЕМ
                        logger.exception("protective_exits.tick failed: %s", e)

                # 2) локальная чистка идемпотентности
                if self._idem is not None and hasattr(self._idem, "cleanup_expired"):
                    try:
                        ttl = int(getattr(self._cfg, "IDEMPOTENCY_TTL_SEC", 300))
                        deleted = self._idem.cleanup_expired(ttl_seconds=ttl)
                        if deleted:
                            logger.info("reconciler: idempotency deleted=%s", deleted)
                    except Exception as e:
                        logger.exception("idempotency cleanup failed: %s", e)

                await asyncio.sleep(self._interval_s)

            except asyncio.CancelledError:
                break
            except Exception as e:
                # <— ЛОГИРУЕМ ЛЮБЫЕ СБОИ ЦИКЛА
                logger.exception("reconciler loop error: %s", e)
                await asyncio.sleep(1.0)

    async def run(self) -> None:
        await self._loop()
