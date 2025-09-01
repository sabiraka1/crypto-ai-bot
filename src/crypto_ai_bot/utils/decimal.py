from __future__ import annotations
from decimal import Decimal, ROUND_DOWN
from typing import Any

Dec = Decimal

def dec(x: Any) -> Decimal:
    return Decimal(str(x))

def q_step(x: Decimal, step_pow10: int, *, rounding: str = ROUND_DOWN) -> Decimal:
    q = Decimal(1).scaleb(step_pow10)
    return x.quantize(q, rounding=rounding)

