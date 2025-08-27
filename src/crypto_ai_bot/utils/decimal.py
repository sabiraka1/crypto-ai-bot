# src/crypto_ai_bot/utils/decimal.py
from __future__ import annotations

from decimal import Decimal, getcontext, ROUND_DOWN, ROUND_HALF_UP, InvalidOperation
from typing import Any, Union

# Безопасная точность для финансовых расчётов
CTX = getcontext()
CTX.prec = 28  # стандартная "денежная" точность
CTX.rounding = ROUND_DOWN

NumberLike = Union[str, int, float, Decimal]


def dec(x: NumberLike) -> Decimal:
    """
    Приведение к Decimal через безопасное str-представление.
    - '1.23' -> Decimal('1.23')
    - 1.23   -> Decimal('1.23')  (внимание: двоичные float)
    - 5      -> Decimal('5')
    """
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot convert to Decimal: {x!r}") from exc


def q_decimals(value: NumberLike, decimals: int, *, rounding=ROUND_DOWN) -> Decimal:
    """
    Квантование по количеству знаков после запятой.
    q_decimals(1.2345, 2) -> 1.23 (ROUND_DOWN по умолчанию)
    """
    v = dec(value)
    q = Decimal(10) ** (-decimals)
    return v.quantize(q, rounding=rounding)


def q_to_step(value: NumberLike, step: NumberLike, *, rounding=ROUND_DOWN) -> Decimal:
    """
    Квантование к ближайшему кратному 'step'.
    Например, step=0.0001 для шага объёма/цены.
    """
    v = dec(value)
    s = dec(step)
    if s <= 0:
        raise ValueError("step must be > 0")
    # quantize к ближайшему кратному step: делим, квант и обратно
    units = (v / s).quantize(Decimal("1"), rounding=rounding)
    return units * s


def q_step(value: NumberLike, precision_or_step: Union[int, NumberLike], *, rounding=ROUND_DOWN) -> Decimal:
    """
    Универсальный помощник:
    - если передан int -> считаем это количеством знаков (decimals)
    - если Decimal/float/str -> считаем это шагом (step)
    """
    if isinstance(precision_or_step, int):
        return q_decimals(value, precision_or_step, rounding=rounding)
    return q_to_step(value, precision_or_step, rounding=rounding)


def q_amount(amount: NumberLike, amount_precision: int) -> Decimal:
    """Округление объёма (amount) по precision.amount биржи."""
    return q_decimals(amount, amount_precision, rounding=ROUND_DOWN)


def q_price(price: NumberLike, price_precision: int) -> Decimal:
    """Округление цены по precision.price биржи."""
    # цену чаще округляют "нормально", но для безопасности используем ROUND_DOWN
    return q_decimals(price, price_precision, rounding=ROUND_DOWN)


def pct(x: NumberLike) -> Decimal:
    """Удобный помощник для процентов: pct(0.5) -> 0.5% == 0.005."""
    return dec(x) / Decimal(100)


def as_str(d: NumberLike, decimals: int = 8) -> str:
    """Форматирование Decimal/числа строкой с фиксированным количеством знаков."""
    return f"{q_decimals(d, decimals):f}"
