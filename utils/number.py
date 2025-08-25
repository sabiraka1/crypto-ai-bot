from __future__ import annotations

from decimal import Decimal, InvalidOperation, getcontext
from typing import Any, Optional

# разумная точность для котировок/объёмов
getcontext().prec = 28


def to_decimal(x: Any, *, default: Optional[Decimal] = Decimal("0")) -> Decimal:
    """
    Безопасная конвертация значений (str|int|float|Decimal|None) в Decimal.
    - None → default
    - float → str(x) (чтобы избежать бинарных артефактов)
    - пробелы/пустые строки → default
    - InvalidOperation → default
    """
    if x is None:
        return default if default is not None else Decimal(0)
    if isinstance(x, Decimal):
        return x
    if isinstance(x, (int,)):
        return Decimal(x)
    if isinstance(x, float):
        # через строку, чтобы не тащить двоичную погрешность
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
    # всё остальное — пробуем как строку
    try:
        return Decimal(str(x))
    except Exception:
        return default if default is not None else Decimal(0)
