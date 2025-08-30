from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from crypto_ai_bot.core.application.ports import StoragePort
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("loop.exits")


class ExitsLoop:
    """
    Следит за открытой позицией и вызывает ProtectiveExits.
    """

    def __init__(
        self,
        *,
        symbol: str,
        storage: StoragePort,
        protective_exits: any,
        exits_interval_sec: float,
        is_paused: Callable[[], bool],
        flight_cm: Callable[[], Awaitable],  # async context manager
    ) -> None:
        self.symbol = symbol
        self.storage = storage
        self.exits = protective_exits
        self.exits_interval_sec = float(max(exits_interval_sec, 0.1))
        self.is_paused = is_paused
        self.flight_cm = flight_cm
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        while not self._stopping:
            try:
                if self.is_paused():
                    await asyncio.sleep(min(1.0, self.exits_interval_sec))
                else:
                    async with self.flight_cm():
                        pos = self.storage.positions.get_position(self.symbol)
                        if pos.base_qty and pos.base_qty > 0:
                            await self.exits.ensure(symbol=self.symbol)
                            check_exec = getattr(self.exits, "check_and_execute", None)
                            if callable(check_exec):
                                try:
                                    await check_exec(symbol=self.symbol)
                                except Exception as exc:
                                    _log.error("check_and_execute_failed", extra={"error": str(exc), "symbol": self.symbol})
            except Exception as exc:
                _log.error("exits_loop_failed", extra={"error": str(exc), "symbol": self.symbol})
            await asyncio.sleep(self.exits_interval_sec)
