from __future__ import annotations

from dataclasses import dataclass

from crypto_ai_bot.core.application.ports import BrokerPort


@dataclass
class OrdersReconciler:
    broker: BrokerPort
    symbol: str

    async def run_once(self) -> None:
        # В базовой версии ничего не тянем из infrastructure напрямую.
        # Оставляем заглушку для последующих расширений (сверка статусов ордеров по бирже)
        return None
