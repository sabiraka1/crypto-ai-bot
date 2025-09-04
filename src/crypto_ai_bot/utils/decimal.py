from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

# Публичный алиас (как и раньше)
Dec = Decimal


def _is_bad_string(s: str) -> bool:
    s = s.strip().lower()
    return s in {"", "none", "nan", "inf", "-inf"}


def dec(x: Any) -> Decimal:
    """
    Безопасное приведение к Decimal.
    - Decimal -> возвращаем как есть
    - float   -> используем Decimal.from_float, чтобы избежать ошибок двоичной репрезентации
    - str     -> пустые/NaN/Inf -> 0
    - иное    -> через str(); ошибки -> 0
    """
    try:
        if isinstance(x, Decimal):
            return x
        if isinstance(x, float):
            # корректная конверсия float -> Decimal
            return Decimal.from_float(x)
        if isinstance(x, (int, bool)):
            return Decimal(int(x))
        s = str(x)
        if _is_bad_string(s):
            return Decimal("0")
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def q_step(x: Decimal, step_pow10: int, *, rounding: str | int = ROUND_DOWN) -> Decimal:
    """
    Квантование по 10**step_pow10 (например, step_pow10=-4 => 0.0001).
    rounding — режим округления decimal (по умолчанию ROUND_DOWN).
    """
    if not isinstance(x, Decimal):
        x = dec(x)
    q = Decimal(1).scaleb(step_pow10)
    try:
        return x.quantize(q, rounding=rounding)  # type: ignore[arg-type]
    except (InvalidOperation, ValueError):
        # fallback: умножаем/делим вручную (редко понадобится)
        scaled = (x / q).to_integral_value(rounding=rounding)  # type: ignore[arg-type]
        return scaled * q


# Доп. утилиты (не ломают API)
def safe_div(a: Any, b: Any, *, default: str = "0") -> Decimal:
    """Безопасное деление с возвратом default при нуле/ошибке."""
    A, B = dec(a), dec(b)
    if B == 0:
        return Decimal(default)
    try:
        return A / B
    except (InvalidOperation, ZeroDivisionError):
        return Decimal(default)


def clamp(x: Any, lo: Any, hi: Any) -> Decimal:
    """Ограничение значения в [lo, hi]."""
    X, L, H = dec(x), dec(lo), dec(hi)
    if X < L:
        return L
    if X > H:
        return H
    return X
