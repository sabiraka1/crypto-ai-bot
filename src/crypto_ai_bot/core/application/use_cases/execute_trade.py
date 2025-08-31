from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.core.application.use_cases.place_order import place_order, PlaceOrderInputs, PlaceOrderResult
from crypto_ai_bot.utils.decimal import dec

@dataclass
class ExecuteInputs:
    symbol: str
    side: str
    quote_amount: Decimal = dec("0")
    base_amount: Decimal = dec("0")
    client_order_id: Optional[str] = None

async def execute_trade(
    *, storage: StoragePort, broker: BrokerPort, bus: EventBusPort, settings: Any, inputs: ExecuteInputs
) -> PlaceOrderResult:
    return await place_order(
        storage=storage,
        broker=broker,
        bus=bus,
        settings=settings,
        inputs=PlaceOrderInputs(
            symbol=inputs.symbol,
            side=inputs.side,
            quote_amount=inputs.quote_amount,
            base_amount=inputs.base_amount,
            client_order_id=inputs.client_order_id,
        ),
    )
