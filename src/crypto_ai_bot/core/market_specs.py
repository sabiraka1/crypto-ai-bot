from __future__ import annotations
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, Optional, Tuple


def _to_dec(x) -> Decimal:
    return Decimal(str(x))


def _quantize_to_decimals(x: float, decimals: Optional[int], *, rounding=ROUND_DOWN) -> float:
    if decimals is None:
        return float(x)
    q = Decimal(1).scaleb(-int(decimals))  # 10^-decimals
    return float(_to_dec(x).quantize(q, rounding=rounding))


def quantize_price(price: float, market: Dict[str, Any]) -> float:
    prec = (market.get("precision") or {}).get("price")
    return _quantize_to_decimals(price, prec, rounding=ROUND_DOWN)


def quantize_amount(amount: float, market: Dict[str, Any], *, side: str) -> float:
    """
    Для покупок/продаж — округляем ВНИЗ до допустимого количества, чтобы не нарушить лимиты.
    """
    prec = (market.get("precision") or {}).get("amount")
    return _quantize_to_decimals(amount, prec, rounding=ROUND_DOWN)


def min_cost(symbol_price: float, amount: float) -> float:
    return float(_to_dec(symbol_price) * _to_dec(amount))


def validate_minimums(*, price: float, amount: float, market: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Проверяет min amount / min cost (notional).
    Возвращает: (ok, reason, needed_value)
      - reason: 'min_amount' | 'min_notional' | None
      - needed_value: сколько минимум нужно (amount для min_amount, notional для min_notional)
    """
    limits = market.get("limits") or {}
    amt_limits = limits.get("amount") or {}
    cost_limits = limits.get("cost") or {}

    min_amt = amt_limits.get("min")
    if min_amt is not None and amount < float(min_amt):
        return False, "min_amount", float(min_amt)

    min_notional = cost_limits.get("min")
    if min_notional is not None and (price * amount) < float(min_notional):
        return False, "min_notional", float(min_notional)

    return True, None, None
