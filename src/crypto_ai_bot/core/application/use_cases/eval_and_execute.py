# src/crypto_ai_bot/core/application/use_cases/eval_and_execute.py
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
    settings: Any,  # Для FEE_PCT_ESTIMATE и др.
    force_action: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Оценивает рынок и делегирует исполнение. Все ограничения — в RiskManager.
    """
    # 1) Рыночные данные (для телеметрии/логов; решение не «жёстко» завязано)
    ticker = await broker.fetch_ticker(symbol)
    mid = (ticker.bid + ticker.ask) / Decimal("2") if ticker.bid and ticker.ask else (ticker.last or Decimal("0"))
    spread_pct = ((ticker.ask - ticker.bid) / mid) if ticker.bid and ticker.ask and mid > 0 else Decimal("0")

    # 2) Текущая позиция
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty or Decimal("0")

    # 3) Решение по стороне (без «sell по спреду»; sell — по force_action/защитным выходам)
    if force_action in ("buy", "sell"):
        side = force_action
    elif position_base <= 0:
        side = "buy"
    else:
        side = "hold"

    # 4) «Hold»: поддерживаем защитные выходы и выходим
    if side == "hold":
        if protective_exits and position_base > 0:
            await protective_exits.ensure(symbol=symbol)
        _log.info("eval_hold", extra={"symbol": symbol, "spread_pct": str(spread_pct), "pos_base": str(position_base)})
        return {"action": "hold", "executed": False}

    # 5) Делегирование в execute_trade (risk-check выполняется там, side-aware)
    result = await execute_trade(
        symbol=symbol,
        side=side,
        storage=storage,
        broker=broker,
        bus=bus,
        exchange=exchange,
        quote_amount=fixed_quote_amount if side == "buy" else None,
        base_amount=None,  # sell возьмёт из позиции
        idempotency_bucket_ms=idempotency_bucket_ms,
        idempotency_ttl_sec=idempotency_ttl_sec,
        risk_manager=risk_manager,
        protective_exits=protective_exits,
        settings=settings,
        force_action=force_action,
    )

    _log.info(
        "eval_done",
        extra={"symbol": symbol, "side": side, "executed": result.get("executed", False), "spread_pct": str(spread_pct)},
    )
    return result
