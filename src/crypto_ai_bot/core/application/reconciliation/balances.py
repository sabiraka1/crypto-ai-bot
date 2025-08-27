from __future__ import annotations

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.utils.logging import get_logger


class BalancesReconciler:
    def __init__(self, broker: IBroker, symbol: str) -> None:
        self._broker = broker
        self._symbol = symbol
        self._log = get_logger("recon.balances")

    async def run_once(self):
        try:
            b = await self._broker.fetch_balance(self._symbol)
        except Exception as exc:
            self._log.error("fetch_balance_failed", extra={"error": str(exc)})
            return {"error": str(exc)}
        return {"free_quote": str(b.free_quote), "free_base": str(b.free_base)}
