"""
Decimal utilities for safe financial calculations.

Critical for trading system accuracy:
- No floating point errors
- Proper rounding for exchange requirements
- PnL calculations
- Percentage operations
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Union, overload

# Public alias
Dec = Decimal

# Type alias for accepted numeric types
NumberLike = Union[Decimal, int, float, str, bool, None]

# ============= CONSTANTS =============
# Pre-created constants for performance (avoid repeated parsing)
ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
TEN = Decimal("10")
HUNDRED = Decimal("100")
THOUSAND = Decimal("1000")

# Common percentages
PERCENT_1 = Decimal("0.01")
PERCENT_10 = Decimal("0.10")
PERCENT_50 = Decimal("0.50")


# ============= CORE CONVERSION =============

def _is_bad_string(s: str) -> bool:
    """Check if string is invalid for Decimal conversion"""
    s = s.strip().lower()
    return s in {"", "none", "nan", "inf", "-inf", "null", "undefined"}


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
    Safe conversion to Decimal.
    
    Behavior:
    - Decimal -> as is
    - float -> Decimal.from_float() (avoids binary representation errors)
    - int/bool -> Decimal(int(x))
    - str -> parse, with bad strings ("", "nan", "inf") -> 0
    - None -> 0
    
    Always returns valid Decimal, never raises.
    """
    try:
        if isinstance(x, Decimal):
            return x
        if isinstance(x, float):
            # Use from_float to avoid str(float) representation issues
            return Decimal.from_float(x)
        if isinstance(x, (int, bool)):
            return Decimal(int(x))
        if x is None:
            return ZERO
        s = str(x)
        if _is_bad_string(s):
            return ZERO
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


# ============= QUANTIZATION & ROUNDING =============

def q_step(x: NumberLike, step_pow10: int, *, rounding: str = ROUND_DOWN) -> Decimal:
    """
    Quantize to step of 10**step_pow10.
    
    Examples:
        q_step(1.2345, -2) -> 1.23 (step = 0.01)
        q_step(1.2345, -4) -> 1.2345 (step = 0.0001)
        
    Args:
        x: Value to quantize
        step_pow10: Power of 10 for step size (-2 means 0.01)
        rounding: Decimal rounding mode (default ROUND_DOWN)
    """
    X = x if isinstance(x, Decimal) else dec(x)
    q = Decimal(1).scaleb(step_pow10)
    try:
        return X.quantize(q, rounding=rounding)
    except (InvalidOperation, ValueError):
        # Fallback: integer division with rounding
        scaled = (X / q).to_integral_value(rounding=rounding)
        return scaled * q


def round_to_step(value: NumberLike, step: NumberLike, *, rounding: str = ROUND_DOWN) -> Decimal:
    """
    Round value to nearest multiple of step.
    Critical for exchange order requirements.
    
    Examples:
        round_to_step(1.2345, 0.01) -> 1.23
        round_to_step(1.2345, 0.5) -> 1.0
        round_to_step(1.7, 0.5) -> 1.5
    """
    v, s = dec(value), dec(step)
    if s == ZERO:
        return v
    
    # Calculate how many steps fit
    steps = (v / s).to_integral_value(rounding=rounding)
    return steps * s


def round_price(price: NumberLike, tick_size: NumberLike) -> Decimal:
    """Round price to exchange tick size (alias for round_to_step)"""
    return round_to_step(price, tick_size, rounding=ROUND_HALF_UP)


def round_amount(amount: NumberLike, lot_size: NumberLike) -> Decimal:
    """Round amount to exchange lot size (always round down to avoid over-ordering)"""
    return round_to_step(amount, lot_size, rounding=ROUND_DOWN)


# ============= ARITHMETIC OPERATIONS =============

def safe_div(a: NumberLike, b: NumberLike, *, default: NumberLike = ZERO) -> Decimal:
    """
    Safe division with default value on error or division by zero.
    
    Returns default when:
    - b is zero
    - Division causes error
    """
    A, B = dec(a), dec(b)
    if B == ZERO:
        return dec(default)
    try:
        return A / B
    except (InvalidOperation, ZeroDivisionError):
        return dec(default)


def clamp(x: NumberLike, lo: NumberLike, hi: NumberLike) -> Decimal:
    """
    Clamp value to range [lo, hi].
    
    Useful for:
    - Limiting position sizes
    - Enforcing min/max order amounts
    """
    X, L, H = dec(x), dec(lo), dec(hi)
    if X < L:
        return L
    if X > H:
        return H
    return X


# ============= PERCENTAGE OPERATIONS =============

def pct(value: NumberLike, percent: NumberLike) -> Decimal:
    """
    Calculate percentage of value.
    
    Examples:
        pct(100, 5) -> 5.0 (5% of 100)
        pct(100, 0.5) -> 0.5 (0.5% of 100)
    """
    return dec(value) * dec(percent) / HUNDRED


def pct_change(old: NumberLike, new: NumberLike) -> Decimal:
    """
    Calculate percentage change from old to new.
    
    Returns:
        Percentage change (e.g., 10.5 means 10.5% increase)
        Returns 0 if old is 0
    """
    old_val = dec(old)
    if old_val == ZERO:
        return ZERO
    return ((dec(new) - old_val) / old_val) * HUNDRED


def pct_diff(a: NumberLike, b: NumberLike) -> Decimal:
    """
    Calculate percentage difference between two values.
    Uses average as base: |a - b| / avg(a, b) * 100
    
    Returns 0 if both are 0.
    """
    A, B = dec(a), dec(b)
    if A == ZERO and B == ZERO:
        return ZERO
    avg = (A + B) / TWO
    if avg == ZERO:
        return ZERO
    return abs(A - B) / avg * HUNDRED


# ============= PNL CALCULATIONS =============

def pnl_amount(entry: NumberLike, exit: NumberLike, quantity: NumberLike) -> Decimal:
    """
    Calculate PnL amount (before fees).
    
    For LONG: (exit - entry) * quantity
    For SHORT: (entry - exit) * quantity  # Not used in SPOT
    """
    return (dec(exit) - dec(entry)) * dec(quantity)


def pnl_pct(entry: NumberLike, exit: NumberLike) -> Decimal:
    """
    Calculate PnL percentage.
    
    Returns:
        Percentage profit/loss (e.g., 5.5 means 5.5% profit)
        Returns 0 if entry is 0
    """
    entry_val = dec(entry)
    if entry_val == ZERO:
        return ZERO
    return ((dec(exit) - entry_val) / entry_val) * HUNDRED


def pnl_with_fees(
    entry: NumberLike,
    exit: NumberLike,
    quantity: NumberLike,
    entry_fee: NumberLike = ZERO,
    exit_fee: NumberLike = ZERO
) -> Decimal:
    """
    Calculate PnL including fees.
    
    Args:
        entry: Entry price
        exit: Exit price
        quantity: Position size
        entry_fee: Fee paid on entry (absolute amount)
        exit_fee: Fee paid on exit (absolute amount)
    """
    gross_pnl = pnl_amount(entry, exit, quantity)
    return gross_pnl - dec(entry_fee) - dec(exit_fee)


def breakeven_price(
    entry: NumberLike,
    quantity: NumberLike,
    total_fees: NumberLike,
    is_long: bool = True
) -> Decimal:
    """
    Calculate breakeven price including fees.
    
    Args:
        entry: Entry price
        quantity: Position size
        total_fees: Total fees (entry + exit)
        is_long: True for long position (SPOT only supports long)
    
    Returns:
        Price at which PnL = 0 after fees
    """
    e, q, f = dec(entry), dec(quantity), dec(total_fees)
    if q == ZERO:
        return e
    
    fee_per_unit = f / q
    if is_long:
        return e + fee_per_unit
    else:
        return e - fee_per_unit  # For future SHORT support


# ============= SPREAD CALCULATIONS =============

def spread_pct(bid: NumberLike, ask: NumberLike) -> Decimal:
    """
    Calculate bid-ask spread as percentage.
    
    Formula: (ask - bid) / mid * 100
    """
    bid_val, ask_val = dec(bid), dec(ask)
    if bid_val == ZERO or ask_val == ZERO:
        return ZERO
    
    mid = (bid_val + ask_val) / TWO
    if mid == ZERO:
        return ZERO
    
    return ((ask_val - bid_val) / mid) * HUNDRED


def mid_price(bid: NumberLike, ask: NumberLike) -> Decimal:
    """Calculate mid price between bid and ask"""
    return (dec(bid) + dec(ask)) / TWO


# ============= POSITION SIZING =============

def position_size_from_risk(
    account_size: NumberLike,
    risk_pct: NumberLike,
    stop_loss_pct: NumberLike
) -> Decimal:
    """
    Calculate position size based on risk management.
    
    Args:
        account_size: Total account value
        risk_pct: Risk per trade (e.g., 2 for 2%)
        stop_loss_pct: Stop loss distance (e.g., 5 for 5%)
    
    Returns:
        Maximum position size to limit risk
    """
    risk_amount = pct(account_size, risk_pct)
    sl_pct = dec(stop_loss_pct)
    if sl_pct == ZERO:
        return ZERO
    
    return risk_amount / (sl_pct / HUNDRED)


def kelly_criterion(
    win_rate: NumberLike,
    avg_win: NumberLike,
    avg_loss: NumberLike
) -> Decimal:
    """
    Calculate optimal position size using Kelly Criterion.
    
    Formula: f = (p * b - q) / b
    where:
        f = fraction to bet
        p = probability of win
        b = ratio of win to loss
        q = probability of loss (1 - p)
    
    Returns:
        Fraction of capital to risk (0 to 1)
        Returns 0 if inputs are invalid
    """
    p = dec(win_rate)
    if p <= ZERO or p >= ONE:
        return ZERO
    
    avg_w, avg_l = dec(avg_win), dec(avg_loss)
    if avg_l == ZERO or avg_w <= ZERO:
        return ZERO
    
    b = avg_w / avg_l  # Win/loss ratio
    q = ONE - p  # Probability of loss
    
    kelly = (p * b - q) / b
    
    # Kelly can be negative (don't bet) or >1 (impossible)
    return clamp(kelly, ZERO, ONE)


# ============= FORMATTING =============

def fmt_decimal(value: NumberLike, decimals: int = 2) -> str:
    """
    Format Decimal for display.
    
    Examples:
        fmt_decimal(1.2345, 2) -> "1.23"
        fmt_decimal(1000.5, 0) -> "1000"
    """
    d = dec(value)
    if decimals == 0:
        return str(int(d))
    
    # Create format string like "0.00"
    q = Decimal(10) ** -decimals
    return str(d.quantize(q, rounding=ROUND_HALF_UP))


def fmt_pct(value: NumberLike, decimals: int = 2) -> str:
    """
    Format as percentage string.
    
    Examples:
        fmt_pct(5.5) -> "5.50%"
        fmt_pct(-3.14159, 1) -> "-3.1%"
    """
    return f"{fmt_decimal(value, decimals)}%"


def fmt_money(value: NumberLike, symbol: str = "$", decimals: int = 2) -> str:
    """
    Format as money string.
    
    Examples:
        fmt_money(1234.56) -> "$1,234.56"
        fmt_money(1234.56, "€") -> "€1,234.56"
    """
    d = dec(value)
    # Format with thousands separator
    formatted = f"{d:,.{decimals}f}"
    return f"{symbol}{formatted}"


# ============= VALIDATION =============

def is_positive(value: NumberLike) -> bool:
    """Check if value is positive (> 0)"""
    return dec(value) > ZERO


def is_negative(value: NumberLike) -> bool:
    """Check if value is negative (< 0)"""
    return dec(value) < ZERO


def is_zero(value: NumberLike, tolerance: NumberLike = ZERO) -> bool:
    """
    Check if value is zero (with optional tolerance).
    
    Args:
        value: Value to check
        tolerance: Maximum difference from zero to consider as zero
    """
    return abs(dec(value)) <= dec(tolerance)


# ============= EXPORT =============

__all__ = [
    # Core
    "Dec",
    "dec",
    "NumberLike",
    "Rounding",
    
    # Constants
    "ZERO",
    "ONE",
    "TWO",
    "TEN",
    "HUNDRED",
    "THOUSAND",
    "PERCENT_1",
    "PERCENT_10",
    "PERCENT_50",
    
    # Quantization & Rounding
    "q_step",
    "round_to_step",
    "round_price",
    "round_amount",
    
    # Arithmetic
    "safe_div",
    "clamp",
    
    # Percentages
    "pct",
    "pct_change",
    "pct_diff",
    
    # PnL
    "pnl_amount",
    "pnl_pct",
    "pnl_with_fees",
    "breakeven_price",
    
    # Spread
    "spread_pct",
    "mid_price",
    
    # Position sizing
    "position_size_from_risk",
    "kelly_criterion",
    
    # Formatting
    "fmt_decimal",
    "fmt_pct",
    "fmt_money",
    
    # Validation
    "is_positive",
    "is_negative",
    "is_zero",
]