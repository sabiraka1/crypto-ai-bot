from __future__ import annotations

from dataclasses import dataclass

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
