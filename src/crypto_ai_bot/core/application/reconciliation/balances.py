from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.utils.decimal import dec


@dataclass
class BalancesReconciler:
    broker: BrokerPort
    symbol: str

    async def run_once(self) -> None:
        # Минимальная сверка доступного баланса чтобы не было лишних зависимостей
        try:
            bal = await self.broker.fetch_balance(self.symbol)
            _ = (bal.free_base or dec("0"))  # доступно
            # здесь может быть логика обновления локального состояния через StoragePort (если потребуется)
        except Exception:
            pass


# Функция-обертка для совместимости с orchestrator
async def reconcile_balances(symbol: str, storage: Any, broker: Any, bus: Any, settings: Any) -> None:
    """Функция-обертка для совместимости с orchestrator."""
    reconciler = BalancesReconciler(broker, symbol)
    await reconciler.run_once()