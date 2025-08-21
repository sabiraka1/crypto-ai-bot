## `symbols.py`
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Tuple
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