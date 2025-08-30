from __future__ import annotations
"""
DEPRECATED: совместимость.
Маршрутизируем в eval_and_execute, чтобы не дублировать бизнес-логику и не тянуть infra-импорты.
"""

from decimal import Decimal
from typing import Optional, Any
from crypto_ai_bot.core.application.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.core.application.ports import BrokerPort, StoragePort, EventBusPort, OrderLike
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.utils.decimal import dec


async def execute_trade(
    *,
    symbol: str,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    force_action: Optional[str],
    risk_manager: RiskManager,
    protective_exits: ProtectiveExits,
    settings: Any,
    fee_estimate_pct: Decimal = dec("0"),
) -> Optional[OrderLike]:
    return await eval_and_execute(
        symbol=symbol, storage=storage, broker=broker, bus=bus, exchange=exchange,
        fixed_quote_amount=fixed_quote_amount, idempotency_bucket_ms=idempotency_bucket_ms,
        idempotency_ttl_sec=idempotency_ttl_sec, force_action=force_action,
        risk_manager=risk_manager, protective_exits=protective_exits,
        settings=settings, fee_estimate_pct=fee_estimate_pct,
    )
