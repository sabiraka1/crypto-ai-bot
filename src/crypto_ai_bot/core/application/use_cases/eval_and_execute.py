from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("usecase.eval")


async def eval_and_execute(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    risk_manager: RiskManager,
    protective_exits: Optional[ProtectiveExits],
    settings: Any,  # Для передачи FEE_PCT_ESTIMATE и других настроек
    force_action: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Оценивает рыночную ситуацию и принимает решение о торговле.
    Делегирует исполнение в execute_trade.
    """
    
    # 1) Получаем рыночные данные для принятия решения
    ticker = await broker.fetch_ticker(symbol)
    mid = (ticker.bid + ticker.ask) / Decimal("2") if ticker.bid and ticker.ask else (ticker.last or Decimal("0"))
    spread_pct = ((ticker.ask - ticker.bid) / mid) if ticker.bid and ticker.ask and mid > 0 else Decimal("0")
    
    # 2) Получаем текущую позицию
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty or Decimal("0")
    
    # 3) Простая логика решения (можно заменить на вызов signal builder)
    # Определяем side на основе позиции
    if force_action in ("buy", "sell"):
        side = force_action
    elif position_base <= 0:
        side = "buy"
    elif position_base > 0 and spread_pct > Decimal("0.01"):
        # Продаем если спред слишком широкий
        side = "sell"
    else:
        side = "hold"
    
    # 4) Если решили держать - просто обновляем protective exits
    if side == "hold":
        if protective_exits and position_base > 0:
            await protective_exits.ensure(symbol=symbol)
        return {"action": "hold", "executed": False}
    
    # 5) Делегируем исполнение в execute_trade
    result = await execute_trade(
        symbol=symbol,
        side=side,
        storage=storage,
        broker=broker,
        bus=bus,
        exchange=exchange,
        quote_amount=fixed_quote_amount if side == "buy" else None,
        base_amount=None,  # execute_trade сам определит из позиции для sell
        idempotency_bucket_ms=idempotency_bucket_ms,
        idempotency_ttl_sec=idempotency_ttl_sec,
        risk_manager=risk_manager,
        protective_exits=protective_exits,
        settings=settings,
        force_action=force_action,
    )
    
    _log.info("eval_completed", extra={
        "symbol": symbol,
        "side": side,
        "result": result.get("action"),
        "executed": result.get("executed", False)
    })
    
    return result