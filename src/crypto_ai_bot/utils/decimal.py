from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Union

JsonNumber = Union[int, float, str, Decimal]

# здравый default на 28 знаков хватает для спота
getcontext().prec = 28

def dec(x: JsonNumber) -> Decimal:
    """Безопасное приведение в Decimal через str(x)."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

def q_step(x: Decimal, step_pow10: int) -> Decimal:
    """Квантование по степени десяти: step_pow10=8 -> 1e-8."""
    q = Decimal(10) ** -step_pow10
    return x.quantize(q, rounding=ROUND_DOWN)
