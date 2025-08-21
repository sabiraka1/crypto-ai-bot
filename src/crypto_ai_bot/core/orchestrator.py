from __future__ import annotations

import asyncio
import logging
from typing import Any, List

from crypto_ai_bot.core.settings import Settings

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Лёгкий планировщик фоновых задач:
      - trade_loop: вызывает execute_trade по SYMBOL с интервалом EVAL_INTERVAL_SEC
      - места под exits_loop и reconcile_loop оставлены, но выключены по умолчанию
    """

    def __init__(self, container: Any) -> None:
        self.c = container
        self.tasks: List[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # стартуем шину (если есть метод start)
        if hasattr(self.c.bus, "start"):
            await self.c.bus.start()

        self.tasks.append(asyncio.create_task(self._trade_loop(), name="trade_loop"))
        # self.tasks.append(asyncio.create_task(self._exits_loop(), name="exits_loop"))
        # self.tasks.append(asyncio.create_task(self._reconcile_loop(), name="reconcile_loop"))

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        # останавливаем шину
        if hasattr(self.c.bus, "stop"):
            await self.c.bus.stop()

    async def _trade_loop(self) -> None:
        s: Settings = self.c.settings
        interval = max(1, int(getattr(s, "EVAL_INTERVAL_SEC", 15) or 15))
        symbol = getattr(s, "SYMBOL", "BTC/USDT")

        from crypto_ai_bot.core.use_cases.execute_trade import execute_trade

        while self._running:
            try:
                res = await execute_trade(
                    cfg=s,
                    broker=self.c.broker,
                    trades_repo=self.c.trades_repo,
                    positions_repo=self.c.positions_repo,
                    exits_repo=self.c.exits_repo,
                    idempotency_repo=self.c.idempotency_repo,
                    limiter=None,
                    symbol=symbol,
                    external={"source": "orchestrator"},
                    bus=self.c.bus,
                    risk_manager=None,  # подключим правила позже по необходимости
                )
                logger.info("execute_trade: %s", res.get("why") or res.get("result", {}))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("trade_loop_error")
            await asyncio.sleep(interval)

    # Заглушки под будущие циклы:
    # async def _exits_loop(self) -> None: ...
    # async def _reconcile_loop(self) -> None: ...
