from __future__ import annotations

from decimal import Decimal, InvalidOperation, getcontext, ROUND_HALF_EVEN, ROUND_DOWN
from typing import Any, Optional

# Один раз на процесс: точность и правило округления
_CTX = getcontext()
_CTX.prec = 28
_CTX.rounding = ROUND_HALF_EVEN


def to_decimal(x: Any, *, default: Optional[Decimal] = Decimal("0")) -> Decimal:
    """
    Безопасная конвертация значений (str|int|float|Decimal|None) в Decimal.
    - None → default
    - float → str(x) (избегаем двоичных артефактов)
    - пустые строки → default
    - InvalidOperation → default
    """
    if x is None:
        return default if default is not None else Decimal(0)
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        try:
            return Decimal(str(x))
        except InvalidOperation:
            return default if default is not None else Decimal(0)
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return default if default is not None else Decimal(0)
        try:
            return Decimal(s)
        except InvalidOperation:
            return default if default is not None else Decimal(0)
    try:
        return Decimal(str(x))
    except Exception:
        return default if default is not None else Decimal(0)


# Удобный alias для единообразия по коду
dec = to_decimal


def q_step(x: Decimal, step_pow10: int, *, rounding=ROUND_DOWN) -> Decimal:
    """
    Квантование по шагу 10^-step_pow10 (удобно для precision 'amount'/'price').
    Пример: q_step(Decimal('0.123456789'), 8) -> Decimal('0.12345678')
    """
    q = Decimal(10) ** -step_pow10
    return x.quantize(q, rounding=rounding)
