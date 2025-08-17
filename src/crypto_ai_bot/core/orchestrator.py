from __future__ import annotations

import asyncio
import time
from typing import Callable, Awaitable, Optional, Dict, Any

from crypto_ai_bot.core.events import AsyncBus as Bus
from crypto_ai_bot.utils import metrics


class Orchestrator:
    """
    Планировщик периодических задач. Работает в одном event loop, не лезет в брокеров напрямую —
    только вызывает публичные use-cases/bot.
    """

    def __init__(self, *, bus: Bus, shutdown_timeout: float = 5.0) -> None:
        self._bus = bus
        self._shutdown_timeout = shutdown_timeout
        self._tasks: set[asyncio.Task] = set()
        self._running = False

    def schedule_every(self, seconds: int, fn: Callable[[], Awaitable[Any]], *, jitter: float = 0.1) -> None:
        """
        Планирование корутин-функции с фиксированным периодом и небольшим джиттером.
        """
        async def _runner():
            try:
                # маленькая рассинхронизация старта
                await asyncio.sleep(seconds * jitter)
                while self._running:
                    t0 = time.perf_counter()
                    try:
                        await fn()
                        metrics.observe("scheduled_task_duration_seconds", time.perf_counter() - t0, {"fn": getattr(fn, "__name__", "anon")})
                    except Exception as e:
                        metrics.inc("scheduled_task_error_total", {"fn": getattr(fn, "__name__", "anon"), "type": type(e).__name__})
                    # выдерживаем период
                    await asyncio.sleep(max(0.0, seconds - (time.perf_counter() - t0)))
            except asyncio.CancelledError:
                pass

        self._tasks.add(asyncio.create_task(_runner()))

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        # отмена и ожидание завершения всех задач
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=self._shutdown_timeout)
        self._tasks.clear()

    # На будущее — хук публикации событий
    def publish(self, event: Dict[str, Any]) -> None:
        try:
            self._bus.publish(event)
        except Exception:
            pass
