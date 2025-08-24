from __future__ import annotations

from dataclasses import dataclass

from ...utils.logging import get_logger
from ..brokers.base import IBroker


@dataclass
class BalancesReconciler:
    """Простейшая проверка, что API баланса отвечает (без жёстких проверок)."""
    broker: IBroker

    def __post_init__(self) -> None:
        self._log = get_logger("reconcile.balances")

    async def run_once(self) -> None:
        try:
            await self.broker.fetch_balance()
        except Exception as exc:
            self._log.error("fetch_balance_failed", extra={"error": str(exc)})
