from __future__ import annotations

from decimal import Decimal
from typing import Dict, Any

from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.utils.logging import get_logger


class PositionsReconciler:
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
        self._log.info(
            "position_checked",
            extra={"symbol": self._symbol, "local_base": str(local_base), "exchange_base": str(base_bal), "diff": str(diff)},
        )
        return {"symbol": self._symbol, "local_base": str(local_base), "exchange_base": str(base_bal), "diff": str(diff), "ok": True}
