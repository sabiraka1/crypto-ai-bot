from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Optional


@dataclass
class SizeConstraints:
    min_quote: Decimal = Decimal("1")
    max_quote: Optional[Decimal] = None
    quote_step_pow10: int = 2  # округлять до цента (1e-2) по умолчанию


def _q_step(x: Decimal, pow10: int) -> Decimal:
    q = Decimal(10) ** -pow10
    return x.quantize(q, rounding=ROUND_DOWN)


def fixed_quote_amount(amount_quote: Decimal, constraints: Optional[SizeConstraints] = None) -> Decimal:
    """Возвращает фиксированную квоту с округлением и ограничениями."""
    c = constraints or SizeConstraints()
    amt = _q_step(amount_quote, c.quote_step_pow10)
    if amt < c.min_quote:
        amt = c.min_quote
    if c.max_quote and amt > c.max_quote:
        amt = c.max_quote
    return amt


def fixed_fractional(quote_balance: Decimal, fraction: float, constraints: Optional[SizeConstraints] = None) -> Decimal:
    """Доля от доступного quote-баланса (например, 0.02 = 2%)."""
    if fraction <= 0:
        return Decimal("0")
    q = quote_balance * Decimal(str(fraction))
    return fixed_quote_amount(q, constraints)


def naive_kelly(win_prob: float, win_loss_ratio: float, quote_balance: Decimal, constraints: Optional[SizeConstraints] = None) -> Decimal:
    """Упрощённый Kelly fraction: f* = p - (1-p)/b. Если <=0 — берём min_quote."""
    p = max(0.0, min(1.0, win_prob))
    b = max(1e-6, win_loss_ratio)
    f_star = p - (1 - p) / b
    if f_star <= 0:
        return fixed_quote_amount(Decimal("0"), constraints)
    q = quote_balance * Decimal(str(f_star))
    return fixed_quote_amount(q, constraints)
