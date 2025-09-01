from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SignalInputs:
    last: Decimal
    bid: Decimal | None
    ask: Decimal | None
    spread_frac: Decimal
    position_base: Decimal
    free_quote: Decimal
    free_base: Decimal


@dataclass(frozen=True)
class Signal:
    action: str              # 'buy' | 'sell' | 'hold'
    strength: Decimal        # 0..1
    meta: dict[str, Any]


def build_signal(inp: SignalInputs) -> Signal:
    """
    Чистая бизнес-логика формирования сигнала (примерная эвристика).
    """
    if inp.position_base <= 0 and inp.spread_frac < Decimal("0.005") and inp.free_quote > Decimal("10"):
        return Signal(action="buy", strength=Decimal("0.6"), meta={"reason": "flat_and_spread_ok"})
    if inp.position_base > 0 and inp.spread_frac > Decimal("0.02"):
        return Signal(action="sell", strength=Decimal("0.4"), meta={"reason": "wide_spread_trim"})
    return Signal(action="hold", strength=Decimal("0.1"), meta={"reason": "no_edge"})


# --- Совместимое имя, которого ждёт старый код:
def build_signals(*args: Any, **kwargs: Any) -> Signal:
    """
    Обёртка для совместимости: старые модули вызывали build_signals().
    Делегируем в build_signal() с теми же аргументами.
    """
    return build_signal(*args, **kwargs)
