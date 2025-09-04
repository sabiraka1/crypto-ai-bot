from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any

Dec = Decimal


def dec(x: Any) -> Decimal:
    """Безопасное приведение к Decimal (None/NaN/Inf -> 0)."""
    try:
        s = str(x)
        if s.lower() in {"none", "nan", "inf", "-inf", ""}:
            return Decimal("0")
        return Decimal(s)
    except Exception:
        return Decimal("0")


def q_step(x: Decimal, step_pow10: int, *, rounding: str = ROUND_DOWN) -> Decimal:
    """Квантование по 10**step_pow10 (например, step_pow10=-4 => 0.0001)."""
    q = Decimal(1).scaleb(step_pow10)
    return x.quantize(q, rounding=rounding)
