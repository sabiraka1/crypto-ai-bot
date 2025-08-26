# src/crypto_ai_bot/utils/decimal.py
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Any

# Единая точность по проекту (совместимо с текущим кодом сигналов)
getcontext().prec = 28

def dec(x: Any, default: str | Decimal = "0") -> Decimal:
    """
    Надёжная конвертация в Decimal:
      - None -> default
      - Decimal -> как есть
      - остальное -> Decimal(str(x))
    """
    if x is None:
        return Decimal(default)
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(default)

def quantize_step(x: Decimal, step_pow10: int) -> Decimal:
    """
    Округление под шаг квотации:
      step_pow10=8 -> шаг 1e-8 и т.п.
    """
    q = Decimal(10) ** -step_pow10
    return x.quantize(q, rounding=ROUND_DOWN)
