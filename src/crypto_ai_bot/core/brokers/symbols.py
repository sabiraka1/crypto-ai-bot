## `symbols.py`
from __future__ import annotations
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Tuple
from ...utils.exceptions import ValidationError

_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")

@dataclass(frozen=True)
class ParsedSymbol:
    base: str
    quote: str

def parse_symbol(symbol: str) -> ParsedSymbol:
    if not isinstance(symbol, str) or "/" not in symbol:
        raise ValidationError("symbol must be like 'BTC/USDT'")
    s = symbol.strip().upper()
    if not _SYMBOL_RE.match(s):
        raise ValidationError("symbol must match [A-Z0-9]+/[A-Z0-9]+")
    base, quote = s.split("/", 1)
    return ParsedSymbol(base=base, quote=quote)

_DEF = "gateio"

def to_exchange_symbol(exchange: str, internal_symbol: str) -> str:
    ex = (exchange or _DEF).lower()
    p = parse_symbol(internal_symbol)
    if ex == "gateio":
        return f"{p.base}_{p.quote}"
    return f"{p.base}/{p.quote}"

def from_exchange_symbol(exchange: str, exchange_symbol: str) -> str:
    ex = (exchange or _DEF).lower()
    s = (exchange_symbol or "").strip().upper()
    if ex == "gateio":
        s = s.replace("-", "_")
        if "_" not in s:
            raise ValidationError("exchange symbol must contain '_' for gateio")
        base, quote = s.split("_", 1)
        return f"{base}/{quote}"
    s = s.replace("-", "/").replace("_", "/")
    parts = s.split("/")
    if len(parts) != 2:
        raise ValidationError("invalid exchange symbol format")
    return f"{parts[0]}/{parts[1]}"

# --- ↓↓↓ ДОБАВЛЕНО НИЖЕ, НЕ ТРОГАЯ ИМЕЮЩЕЕСЯ parse_symbol и т.п. ↓↓↓

def _dec(x: Any) -> Decimal:
    from decimal import Decimal as _D
    if x is None:
        return _D("0")
    if isinstance(x, _D):
        return x
    return _D(str(x))

@dataclass
class MarketInfo:
    symbol: str
    base: str
    quote: str
    base_step: Decimal
    quote_step: Decimal
    price_tick: Decimal
    min_base: Decimal
    min_quote: Decimal
    min_notional_quote: Decimal

def market_info_from_ccxt(symbol: str, m: Dict[str, Any]) -> MarketInfo:
    p = m.get("precision", {}) or {}
    L = m.get("limits", {}) or {}
    amount_min = _dec((L.get("amount") or {}).get("min") or 0)
    cost_min   = _dec((L.get("cost") or {}).get("min") or 0)     # ~ minNotional in quote
    price_tick = _dec(p.get("price") or 0)
    # шаг базового/квотируемого (если нет явного шага — подстрахуемся малым значением)
    base_step  = _dec(p.get("amount") or "0.00000001")
    quote_step = _dec("0.00000001")
    return MarketInfo(
        symbol=symbol,
        base=m.get("base") or symbol.split("/")[0],
        quote=m.get("quote") or symbol.split("/")[1],
        base_step=base_step,
        quote_step=quote_step,
        price_tick=price_tick if price_tick > 0 else _dec("0.00000001"),
        min_base=amount_min,
        min_quote=_dec(0),
        min_notional_quote=cost_min,
    )

def round_base_step(amount_base: Decimal, step: Decimal, *, rounding=ROUND_DOWN) -> Decimal:
    if step is None or step <= 0:
        return amount_base
    # к ближайшей сетке вниз
    q = (amount_base / step).to_integral_value(rounding=rounding)
    return q * step

def ensure_min_notional_ok(amount_quote: Decimal, price: Decimal, min_notional_quote: Decimal) -> None:
    if min_notional_quote and (amount_quote < min_notional_quote):
        raise ValidationError(f"notional {amount_quote} < min_notional {min_notional_quote}")