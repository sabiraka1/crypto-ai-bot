from __future__ import annotations

from decimal import Decimal, getcontext, ROUND_HALF_EVEN, ROUND_DOWN
from typing import Any

# Глобальная настройка контекста (один раз на процесс)
CTX = getcontext()
CTX.prec = 28
CTX.rounding = ROUND_HALF_EVEN

def dec(x: Any) -> Decimal:
    """Надёжная конвертация в Decimal без накопления двоичных артефактов."""
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal("0")
    return Decimal(str(x))

def q_step(x: Decimal, step_pow10: int, *, rounding=ROUND_DOWN) -> Decimal:
    """Квантование по 10^-step_pow10 (удобно для amount/price precision)."""
    q = Decimal(10) ** -step_pow10
    return x.quantize(q, rounding=rounding)
