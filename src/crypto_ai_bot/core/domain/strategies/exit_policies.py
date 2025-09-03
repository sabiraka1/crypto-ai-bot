from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_ai_bot.utils.decimal import dec


@dataclass
class ExitPlan:
    entry_price: Decimal
    sl_price: Decimal | None = None
    tp_price: Decimal | None = None
    trailing_pct: float | None = None
    trail_max_price: Decimal | None = None


def make_fixed_sl_tp(*, entry_price: Decimal, sl_pct: float, tp_pct: float | None = None) -> ExitPlan:
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


# Классы-обертки для совместимости с __init__.py и другими модулями
class StopLossPolicy:
    """Политика стоп-лосса."""
    def __init__(self, sl_pct: float = 2.0):
        self.sl_pct = sl_pct

    def create_plan(self, entry_price: Decimal) -> ExitPlan:
        return make_fixed_sl_tp(entry_price=entry_price, sl_pct=self.sl_pct)

    def check(self, plan: ExitPlan, last: Decimal) -> str:
        return should_exit(plan, last)


class TakeProfitPolicy:
    """Политика тейк-профита."""
    def __init__(self, tp_pct: float = 5.0):
        self.tp_pct = tp_pct

    def create_plan(self, entry_price: Decimal) -> ExitPlan:
        return make_fixed_sl_tp(entry_price=entry_price, sl_pct=0, tp_pct=self.tp_pct)

    def check(self, plan: ExitPlan, last: Decimal) -> str:
        return should_exit(plan, last)


class TrailingStopPolicy:
    """Политика трейлинг-стопа."""
    def __init__(self, trailing_pct: float = 3.0):
        self.trailing_pct = trailing_pct

    def create_plan(self, entry_price: Decimal) -> ExitPlan:
        return ExitPlan(
            entry_price=entry_price,
            trailing_pct=self.trailing_pct,
            trail_max_price=entry_price
        )

    def update(self, plan: ExitPlan, last: Decimal) -> ExitPlan:
        return update_trailing_stop(plan, last)

    def check(self, plan: ExitPlan, last: Decimal) -> str:
        return should_exit(plan, last)
