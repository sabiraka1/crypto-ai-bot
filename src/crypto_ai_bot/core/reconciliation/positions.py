from __future__ import annotations

from typing import Any, Dict, Optional
from decimal import Decimal

from ..storage.facade import Storage
from ..risk.protective_exits import ProtectiveExits
from ...utils.logging import get_logger
from ...utils.metrics import inc, timer

# для /status
_last_status: Dict[str, Any] | None = None


def get_last_status() -> Optional[Dict[str, Any]]:
    return _last_status


class PositionsReconciler:
    """
    Мягкая сверка позиции:
    - Если позиция > 0 — вызываем ProtectiveExits.ensure(symbol=...)
    - Только лог/метрики, бизнес-логика не меняется
    """

    def __init__(self, *, storage: Storage, exits: ProtectiveExits, symbol: str) -> None:
        self._log = get_logger("reconcile.positions")
        self._storage = storage
        self._exits = exits
        self._symbol = symbol

    async def run_once(self) -> None:
        global _last_status

        with timer("reconcile_positions_ms", {"symbol": self._symbol}):
            try:
                pos = self._storage.positions.get_position(self._symbol)
                base = Decimal(str(pos.base_qty or "0"))
                if base > 0:
                    await self._exits.ensure(symbol=self._symbol)
                    inc("reconcile_positions", {"symbol": self._symbol, "has_pos": "1"})
                    self._log.info("ensure_exits_done", extra={"symbol": self._symbol, "base_qty": str(base)})
                    _last_status = {"ok": True, "has_pos": True, "base_qty": str(base)}
                else:
                    inc("reconcile_positions", {"symbol": self._symbol, "has_pos": "0"})
                    self._log.info("no_position", extra={"symbol": self._symbol})
                    _last_status = {"ok": True, "has_pos": False, "base_qty": "0"}
            except Exception as exc:
                inc("reconcile_positions", {"symbol": self._symbol, "status": "failed"})
                self._log.error("positions_reconcile_failed", extra={"error": str(exc)})
                _last_status = {"ok": False, "error": str(exc)}
