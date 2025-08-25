from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

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

    _last_beat_ms: int = 0

    def beat(self) -> None:
        self._last_beat_ms = now_ms()

    async def check_and_trigger(self) -> None:
        if self._last_beat_ms == 0:
            self._last_beat_ms = now_ms()
            return
        if now_ms() - self._last_beat_ms <= self.timeout_ms:
            return

        # Просрочен heartbeat — аварийно закрываем позицию (market sell base)
        base_qty = self.storage.positions.get_base_qty(self.symbol) or Decimal("0")
        if base_qty > 0:
            try:
                await self.broker.create_market_sell_base(self.symbol, base_qty)
                self.storage.audit.log("dms.emergency_close", {
                    "symbol": self.symbol, "base_amount": str(base_qty)
                })
                _log.error("emergency_close_executed", extra={"symbol": self.symbol, "base": str(base_qty)})
            finally:
                self._last_beat_ms = now_ms()  # сбрасываем, чтобы не дёргать без конца
