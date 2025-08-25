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

    def beat(self) -> None:
        self._last_beat_ms = now_ms()

    async def check_and_trigger(self) -> None:
        if self._last_beat_ms is None:
            return
        if (now_ms() - self._last_beat_ms) > self.timeout_ms:
            # Минимальная реакция: залогировать, в проде — вызвать аварийный выход.
            _log.error("dead_mans_switch_triggered", extra={"symbol": self.symbol, "timeout_ms": self.timeout_ms})
            # Здесь можно добавить безопасную ликвидацию позиции (sell base), если политика позволяет.