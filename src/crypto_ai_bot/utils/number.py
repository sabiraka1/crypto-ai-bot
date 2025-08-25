from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def to_decimal(x: Any) -> Decimal:
    """
    Унифицированная и безопасная конвертация в Decimal.
    - Бережно обращается с типами (str/float/int/Decimal)
    - Избегает двусмысленностей через Decimal(str(...))
    - Явно валится на мусорных значениях

    Пример:
        to_decimal("1.23") -> Decimal("1.23")
        to_decimal(1.23)   -> Decimal("1.23")   # через str, чтобы не тянуть бинарные артефакты
    """
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"cannot convert to Decimal: {x!r}") from exc


def quantize_step(amount: Decimal, step: Decimal) -> Decimal:
    """
    Аккуратная нормализация количества к шагу (precision/lot).
    Не завышает количество (используем floor), чтобы не улетать ниже min-лимитов биржи.

    Пример:
        quantize_step(Decimal("0.001234"), Decimal("0.0001")) -> Decimal("0.0012")
    """
    if step <= 0:
        return amount
    # floor до ближайшего шага
    return (amount // step) * step
