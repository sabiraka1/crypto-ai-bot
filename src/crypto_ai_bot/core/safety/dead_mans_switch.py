from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..brokers.base import IBroker
from ..storage.facade import Storage
from ...utils.time import now_ms
from ...utils.logging import get_logger

_log = get_logger("safety.dms")


@dataclass
class DeadMansSwitch:
    storage: Storage
    broker: IBroker
    symbol: str
    timeout_ms: int = 120_000

    _last_beat_ms: Optional[int] = None
    _created_ms: int = 0

    def __post_init__(self) -> None:
        # если beat ещё не был — считаем временем отсчёта момент создания
        self._created_ms = now_ms()
        if self._last_beat_ms is None:
            self._last_beat_ms = self._created_ms

    def beat(self) -> None:
        self._last_beat_ms = now_ms()

    async def check_and_trigger(self) -> None:
        now = now_ms()
        last = self._last_beat_ms or self._created_ms
        if (now - last) > self.timeout_ms:
            _log.error("dead_mans_switch_triggered", extra={"symbol": self.symbol, "timeout_ms": self.timeout_ms, "last": last, "now": now})
            # точка расширения: безопасная ликвидация позиции (sell base) по политике