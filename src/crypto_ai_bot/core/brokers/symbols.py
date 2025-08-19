# src/crypto_ai_bot/core/brokers/symbols.py
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional, Tuple


# ----------------------- нормализация символов -----------------------
def _split(sym: str) -> Tuple[str, str]:
    s = sym.replace("_", "/").upper().strip()
    if "/" in s:
        base, quote = s.split("/", 1)
    else:
        # простая эвристика: известные суффиксы квоты
        if s.endswith("USDT"):
            base, quote = s[:-4], "USDT"
        elif s.endswith("USD"):
            base, quote = s[:-3], "USD"
        else:
            mid = max(3, len(s) // 2)
            base, quote = s[:mid], s[mid:]
    return base, quote


def normalize_symbol(symbol: str, exchange: str | None = None) -> str:
    """
    Унифицируем во внутренний вид CCXT 'BASE/QUOTE'.
    """
    base, quote = _split(symbol)
    return f"{base}/{quote}"


def to_exchange_symbol(symbol: str, exchange: str = "binance") -> str:
    """
    Преобразование во внешний формат конкретной биржи:
      - binance/bybit/okx → BASE/QUOTE
      - gate/gateio      → BASE_USDT (подчёркивание)
    """
    base, quote = _split(symbol)
    ex = (exchange or "binance").lower()
    if ex in {"binance", "bybit", "okx"}:
        return f"{base}/{quote}"
    if ex in {"gate", "gateio"}:
        return f"{base}_{quote}"
    return f"{base}/{quote}"


# ----------------------- правила точности и минимумов -----------------------
def _to_dec(x) -> Decimal:
    return Decimal(str(x))


def _quantize_to_decimals(x: float, decimals: Optional[int], *, rounding=ROUND_DOWN) -> float:
    if decimals is None:
        return float(x)
    q = Decimal(1).scaleb(-int(decimals))  # 10^-decimals
    return float(_to_dec(x).quantize(q, rounding=rounding))


def quantize_price(price: float, market: Dict[str, Any]) -> float:
    """
    Округление цены вниз по точности биржи (market['precision']['price']).
    """
    prec = (market.get("precision") or {}).get("price")
    return _quantize_to_decimals(price, prec, rounding=ROUND_DOWN)


def quantize_amount(amount: float, market: Dict[str, Any], *, side: str) -> float:
    """
    Округление количества вниз по точности биржи (market['precision']['amount']).
    Для покупок/продаж округляем вниз, чтобы не нарушить лимиты.
    """
    prec = (market.get("precision") or {}).get("amount")
    return _quantize_to_decimals(amount, prec, rounding=ROUND_DOWN)


def min_cost(symbol_price: float, amount: float) -> float:
    return float(_to_dec(symbol_price) * _to_dec(amount))


def validate_minimums(*, price: float, amount: float, market: Dict[str, Any]):
    """
    Проверяет min amount / min cost (notional).
    Возвращает: (ok: bool, reason: Optional[str], needed_value: Optional[float])
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
