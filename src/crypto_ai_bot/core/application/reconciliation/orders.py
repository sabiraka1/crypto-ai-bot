from __future__ import annotations

from dataclasses import dataclass

from crypto_ai_bot.core.application.ports import BrokerPort


@dataclass
class OrdersReconciler:
    broker: BrokerPort
    symbol: str

    async def run_once(self) -> None:
        # In the basic version we don't pull anything from infrastructure directly.
        # Leaving stub for future extensions (order status reconciliation)
        return None
