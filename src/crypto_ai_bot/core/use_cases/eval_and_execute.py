from __future__ import annotations
from decimal import Decimal
from typing import Optional, TYPE_CHECKING, Dict, Any
from ..events.bus import AsyncEventBus
from ..brokers.base import IBroker
from ..storage.facade import Storage
from .execute_trade import execute_trade
from ...utils.metrics import timer

if TYPE_CHECKING:  # только для подсветки типов в IDE
    from .execute_trade import execute_trade as _ET  # noqa


class ValidationError(ValueError):
    """Custom validation error for eval_and_execute"""
    pass


async def eval_and_execute(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: Optional[AsyncEventBus],
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    risk_manager: Optional[object] = None,
    protective_exits: Optional[object] = None,
    force_action: Optional[str] = None,
    force_amount: Optional[Decimal] = None,
) -> Dict[str, Any]:
    """Комбинированный фасад: оценить и (при необходимости) выполнить."""

    with timer("eval_and_execute_total_ms", {"symbol": symbol}):
        with timer("execute_trade_ms", {"symbol": symbol}):
            result = await execute_trade(
                symbol=symbol,
                storage=storage,
                broker=broker,
                bus=bus,
                exchange=exchange,
                fixed_quote_amount=fixed_quote_amount,
                idempotency_bucket_ms=idempotency_bucket_ms,
                idempotency_ttl_sec=idempotency_ttl_sec,
                risk_manager=risk_manager,  # type: ignore[arg-type]
                protective_exits=protective_exits,  # type: ignore[arg-type]
                force_action=force_action,
                force_amount=force_amount,
            )
    return result