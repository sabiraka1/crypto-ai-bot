## `eval_and_execute.py`
from __future__ import annotations
from decimal import Decimal
from typing import Optional
from ..events.bus import AsyncEventBus
from ..brokers.base import IBroker
from ..storage.facade import Storage
from .execute_trade import execute_trade, ExecuteResult
from ...utils.metrics import timer

# ValidationError из settings.py
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
) -> ExecuteResult:
    """Комбинированный фасад: оценить и (при необходимости) выполнить.
    Если force_action задан, политика оценки игнорируется и выполняется указанное действие.
    """
    
    # Обернем весь процесс в таймер
    with timer("eval_and_execute_total_ms", {"symbol": symbol}, unit="ms"):
        # 1) Построение фич/тикера/контекста и принятие решения происходит в execute_trade
        with timer("execute_trade_ms", {"symbol": symbol}, unit="ms"):
            result = await execute_trade(
                symbol=symbol,
                storage=storage,
                broker=broker,
                bus=bus,
                exchange=exchange,
                fixed_quote_amount=fixed_quote_amount,
                idempotency_bucket_ms=idempotency_bucket_ms,
                idempotency_ttl_sec=idempotency_ttl_sec,
                risk_manager=risk_manager,
                protective_exits=protective_exits,
                force_action=force_action,
                force_amount=force_amount,
            )
    
    return result