from __future__ import annotations

from decimal import Decimal
from typing import Dict, Any

from ..storage.facade import Storage
from ..brokers.base import IBroker
from ..brokers.symbols import parse_symbol
from ...utils.logging import get_logger


class PositionsReconciler:
    """Сверка позиции: локальная позиция vs. биржевой баланс по базовой валюте (spot/long-only)."""

    def __init__(self, *, storage: Storage, broker: IBroker, symbol: str) -> None:
        self._storage = storage
        self._broker = broker
        self._symbol = symbol
        self._log = get_logger("recon.positions")

    async def run_once(self) -> Dict[str, Any]:
        sym = parse_symbol(self._symbol)
        local_base = self._storage.positions.get_base_qty(self._symbol) or Decimal("0")
        try:
            bal = await self._broker.fetch_balance(self._symbol)
        except Exception as exc:
            self._log.error("fetch_balance_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

        base_bal = bal.free_base
        diff = base_bal - local_base
        ok = True
        self._log.info(
            "position_checked",
            extra={"symbol": self._symbol, "local_base": str(local_base), "exchange_base": str(base_bal), "diff": str(diff)},
        )
        return {"symbol": self._symbol, "local_base": str(local_base), "exchange_base": str(base_bal), "diff": str(diff), "ok": ok}