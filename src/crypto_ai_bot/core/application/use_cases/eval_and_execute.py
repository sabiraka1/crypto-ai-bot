from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.use_cases.place_order import (
    place_order,
    PlaceOrderInputs,
    PlaceOrderResult,
)
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.eval_and_execute")


@dataclass
class EvalInputs:
    symbol: str
    quote_amount: Decimal


@dataclass
class EvalResult:
    ok: bool
    reason: str = ""
    order: Optional[Any] = None


async def eval_and_execute(
    *,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    risk: RiskManager,
    settings: Any,
    inputs: EvalInputs,
) -> EvalResult:
    """
    ЕДИНАЯ точка принятия решения + исполнение:
    - бюджет/риск проверяем ЗДЕСЬ (RiskManager.allow)
    - спред/проскальзывание и фактическое размещение ордера выполняет place_order
    - дублирующих проверок нет
    """
    sym = inputs.symbol
    q_amt = inputs.quote_amount

    # ---- ЕДИНЫЙ бюджет/риск-гейт ----
    ok, reason = risk.allow(symbol=sym, action="buy", quote_amount=q_amt, base_amount=None)
    if not ok:
        inc("trade.blocked", {"reason": reason})
        await bus.publish("trade.blocked", {"symbol": sym, "reason": reason})
        return EvalResult(ok=False, reason=reason)

    # ---- Исполнение через единый исполнитель (place_order) ----
    res: PlaceOrderResult = await place_order(
        storage=storage,
        broker=broker,
        bus=bus,
        settings=settings,
        inputs=PlaceOrderInputs(symbol=sym, side="buy", quote_amount=q_amt),
    )
    return EvalResult(ok=res.ok, reason=res.reason, order=res.order)
