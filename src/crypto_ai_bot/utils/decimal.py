from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Optional, Union, overload

# Публичный алиас (как и раньше)
Dec = Decimal

# Принимаемые типы вместо Any
NumberLike = Union[Decimal, int, float, str, bool, None]


def _is_bad_string(s: str) -> bool:
    s = s.strip().lower()
    return s in {"", "none", "nan", "inf", "-inf"}


# ---------- dec(...) ----------
@overload
def dec(x: Decimal) -> Decimal: ...
@overload
def dec(x: int) -> Decimal: ...
@overload
def dec(x: float) -> Decimal: ...
@overload
def dec(x: str) -> Decimal: ...
@overload
def dec(x: bool) -> Decimal: ...
@overload
def dec(x: None) -> Decimal: ...
def dec(x: NumberLike) -> Decimal:
    """
    Безопасное приведение к Decimal.

    Поведение:
      - Decimal -> как есть
      - float   -> Decimal.from_float(..) (без двоичной погрешности str(float))
      - int/bool-> Decimal(int(x))
      - str     -> пустые/NaN/Inf -> 0
      - None    -> 0
    """
    try:
        if isinstance(x, Decimal):
            return x
        if isinstance(x, float):
            return Decimal.from_float(x)
        if isinstance(x, (int, bool)):
            return Decimal(int(x))
        if x is None:
            return Decimal("0")
        s = str(x)
        if _is_bad_string(s):
            return Decimal("0")
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


# ---------- q_step(...) ----------
def q_step(x: NumberLike, step_pow10: int, *, rounding: str = ROUND_DOWN) -> Decimal:
    """
    Квантование по шагу 10**step_pow10 (например, step_pow10=-4 => 0.0001).
    rounding — режим округления decimal (по умолчанию ROUND_DOWN).
    """
    X = x if isinstance(x, Decimal) else dec(x)
    q = Decimal(1).scaleb(step_pow10)
    try:
        return X.quantize(q, rounding=rounding)
    except (InvalidOperation, ValueError):
        # Fallback: целочисленное деление с округлением
        scaled = (X / q).to_integral_value(rounding=rounding)
        return scaled * q


# ---------- safe_div(...) ----------
def safe_div(a: NumberLike, b: NumberLike, *, default: NumberLike = "0") -> Decimal:
    """Безопасное деление с возвратом default при нуле/ошибке."""
    A, B = dec(a), dec(b)
    if B == 0:
        return dec(default)
    try:
        return A / B
    except (InvalidOperation, ZeroDivisionError):
        return dec(default)


# ---------- clamp(...) ----------
def clamp(x: NumberLike, lo: NumberLike, hi: NumberLike) -> Decimal:
    """Ограничение значения в [lo, hi]."""
    X, L, H = dec(x), dec(lo), dec(hi)
    if X < L:
        return L
    if X > H:
        return H
    return X
