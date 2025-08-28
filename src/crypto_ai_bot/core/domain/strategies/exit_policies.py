from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from crypto_ai_bot.utils.decimal import dec
from typing import Optional


@dataclass
class ExitPlan:
    entry_price: Decimal
    sl_price: Optional[Decimal] = None
    tp_price: Optional[Decimal] = None
    trailing_pct: Optional[float] = None
    trail_max_price: Optional[Decimal] = None


def make_fixed_sl_tp(*, entry_price: Decimal, sl_pct: float, tp_pct: Optional[float] = None) -> ExitPlan:
    """Фиксированный SL/TP в процентах от входа."""
    e = dec(str(entry_price))
    sl = e * (dec("1") - dec(str(sl_pct)) / dec("100"))
    tp = None
    if tp_pct is not None:
        tp = e * (dec("1") + dec(str(tp_pct)) / dec("100"))
    return ExitPlan(entry_price=e, sl_price=sl, tp_price=tp)


def update_trailing_stop(plan: ExitPlan, last: Decimal) -> ExitPlan:
    """Обновляет trailing stop при росте цены."""
    if plan.trailing_pct is None:
        return plan
    if plan.trail_max_price is None or last > plan.trail_max_price:
        plan.trail_max_price = last
        # SL подтягиваем вверх на trailing_pct
        trail = dec(str(plan.trailing_pct)) / dec("100")
        plan.sl_price = last * (dec("1") - trail)
    return plan


def should_exit(plan: ExitPlan, last: Decimal) -> str:
    """Возврат: 'sl' | 'tp' | 'hold'."""
    if plan.sl_price is not None and last <= plan.sl_price:
        return "sl"
    if plan.tp_price is not None and last >= plan.tp_price:
        return "tp"
    return "hold"
