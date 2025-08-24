from __future__ import annotations

from ..storage.facade import Storage
from ..risk.protective_exits import ProtectiveExits
from ...utils.logging import get_logger

class PositionsReconciler:
    """
    Мягкая сверка позиции: если есть позиция — убеждаемся, что SL/TP установлены через ProtectiveExits.ensure().
    Изменений в БД не делает (кроме того, что может поставить защитные ордера).
    """

    def __init__(self, *, storage: Storage, exits: ProtectiveExits, symbol: str) -> None:
        self._log = get_logger("reconcile.positions")
        self._storage = storage
        self._exits = exits
        self._symbol = symbol

    async def run_once(self) -> None:
        try:
            pos = self._storage.positions.get_position(self._symbol)
            if pos.base_qty and pos.base_qty > 0:
                await self._exits.ensure(symbol=self._symbol)
                self._log.info("ensure_exits_done", extra={"symbol": self._symbol, "base_qty": str(pos.base_qty)})
            else:
                self._log.info("no_position", extra={"symbol": self._symbol})
        except Exception as exc:
            self._log.error("positions_reconcile_failed", extra={"error": str(exc)})
