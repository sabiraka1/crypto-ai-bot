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
    Единая точка решения + исполнение.
    1) Лимиты в день (UTC): кол-во ордеров и дневной оборот в котируемой валюте.
    2) Бюджет/риск (RiskManager.allow).
    3) Исполнение через place_order (внутри — slippage gate).
    """
    sym = inputs.symbol
    q_amt = inputs.quote_amount

    # ---- Safety budget (UTC day) ----
    try:
        max_orders = int(getattr(settings, "SAFETY_MAX_ORDERS_PER_DAY", 0) or 0)
        if max_orders > 0:
            n = storage.trades.count_orders_last_minutes(sym, 24 * 60)  # близкая оценка «за 24 часа»
            if n >= max_orders:
                reason = f"day_orders_limit:{n}>={max_orders}"
                inc("trade.blocked", {"reason": "day_orders_limit"})
                await bus.publish("trade.blocked", {"symbol": sym, "reason": reason})
                return EvalResult(ok=False, reason=reason)
    except Exception as exc:
        _log.warning("safety_orders_check_failed", extra={"error": str(exc)})

    try:
        day_turnover_limit = Decimal(str(getattr(settings, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", "") or "0"))
        if day_turnover_limit > 0:
            spent = storage.trades.daily_turnover_quote(sym)  # ожидаем UTC
            if spent + q_amt > day_turnover_limit:
                reason = f"day_turnover_limit:{spent + q_amt}>{day_turnover_limit}"
                inc("trade.blocked", {"reason": "day_turnover_limit"})
                await bus.publish("trade.blocked", {"symbol": sym, "reason": reason})
                return EvalResult(ok=False, reason=reason)
    except Exception as exc:
        _log.warning("safety_turnover_check_failed", extra={"error": str(exc)})

    # ---- ЕДИНЫЙ бюджет/риск-гейт ----
    ok, reason = risk.allow(symbol=sym, action="buy", quote_amount=q_amt, base_amount=None)
    if not ok:
        inc("trade.blocked", {"reason": reason})
        await bus.publish("trade.blocked", {"symbol": sym, "reason": reason})
        return EvalResult(ok=False, reason=reason)

    # ---- Исполнение через единый исполнитель ----
    res: PlaceOrderResult = await place_order(
        storage=storage,
        broker=broker,
        bus=bus,
        settings=settings,
        inputs=PlaceOrderInputs(symbol=sym, side="buy", quote_amount=q_amt),
    )
    return EvalResult(ok=res.ok, reason=res.reason, order=res.order)
