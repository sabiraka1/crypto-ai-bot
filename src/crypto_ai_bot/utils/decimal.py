# src/crypto_ai_bot/utils/decimal.py
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, getcontext
from typing import Any

CTX = getcontext()
CTX.prec = 28
CTX.rounding = ROUND_HALF_EVEN

def dec(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal("0")
    return Decimal(str(x))

def q_step(x: Decimal, step_pow10: int, *, rounding=ROUND_DOWN) -> Decimal:
    q = Decimal(10) ** -step_pow10
    return x.quantize(q, rounding=rounding)
