from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ParsedSymbol:
    base: str
    quote: str

def parse_symbol(s: str) -> ParsedSymbol:
    s = (s or "").upper().replace("-", "/").replace(":", "/").replace("_", "/")
    if "/" not in s:
        if len(s) >= 7:
            return ParsedSymbol(base=s[:-4], quote=s[-4:])
        raise ValueError(f"Invalid symbol: {s}")
    base, quote = s.split("/", 1)
    return ParsedSymbol(base=base, quote=quote)

def canonical(symbol: str) -> str:
    p = parse_symbol(symbol)
    return f"{p.base}/{p.quote}"
