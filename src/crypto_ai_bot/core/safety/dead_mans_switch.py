from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ...utils.time import now_ms
from ...utils.logging import get_logger
from ..storage.facade import Storage
from ..brokers.base import IBroker


@dataclass
class DeadMansSwitch:
    """
    Dead Man's Switch (DMS):
    - beat() — обновляет «пульс»
    - check_and_trigger() — если слишком долго нет пульса, экстренно закрывает позицию
    """
    storage: Storage
    broker: IBroker
    symbol: str
    timeout_ms: int = 120_000  # 2 минуты

    _last_beat_ms: int = 0

    def beat(self) -> None:
        self._last_beat_ms = now_ms()

    async def check_and_trigger(self) -> Optional[str]:
        """
        Возвращает строку-причину, если был выполнен экстренный выход, иначе None.
        """
        log = get_logger("safety.dms")
        if self._last_beat_ms == 0:
            self._last_beat_ms = now_ms()
            return None

        if (now_ms() - self._last_beat_ms) < self.timeout_ms:
            return None

        # таймаут — закроем позицию, если есть
        pos = self.storage.positions.get_position(self.symbol)
        base_qty: Decimal = pos.base_qty or Decimal("0")
        if base_qty > 0:
            try:
                await self.broker.create_market_sell_base(self.symbol, amount_base=base_qty)
                log.error("emergency_exit_executed", extra={"symbol": self.symbol, "amount_base": str(base_qty)})
                return "emergency_exit"
            except Exception as exc:
                log.error("emergency_exit_failed", extra={"symbol": self.symbol, "error": str(exc)})
                return "emergency_exit_failed"
        return "no_position"
