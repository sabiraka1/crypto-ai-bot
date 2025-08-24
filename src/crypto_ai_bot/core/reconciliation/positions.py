from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ...utils.logging import get_logger
from ..storage.facade import Storage
from ..risk.protective_exits import ProtectiveExits


@dataclass
class PositionsReconciler:
    """Гарантирует, что при наличии позиции защитные выходы на месте."""
    storage: Storage
    exits: ProtectiveExits
    symbol: str

    def __post_init__(self) -> None:
        self._log = get_logger("reconcile.positions")

    async def run_once(self) -> None:
        pos = self.storage.positions.get_position(self.symbol)
        base = Decimal(pos.base_qty or 0)
        if base > 0:
            try:
                await self.exits.ensure(symbol=self.symbol)
            except Exception as exc:
                self._log.error("ensure_failed", extra={"error": str(exc)})
