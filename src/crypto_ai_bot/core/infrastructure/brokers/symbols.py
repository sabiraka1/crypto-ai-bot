from __future__ import annotations
from dataclasses import dataclass

# В коде везде используем canonical: "BASE/QUOTE" (например "BTC/USDT").
# Здесь даём безопасные преобразования под/с форматов бирж.

@dataclass(frozen=True)
class ParsedSymbol:
    base: str
    quote: str

def parse_symbol(s: str) -> ParsedSymbol:
    s = (s or "").upper().replace("-", "/").replace(":", "/").replace("_", "/")
    if "/" not in s:
        # последний 3-4 символа считаем QUOTE, остальное BASE (fallback)
        if len(s) >= 7:
            return ParsedSymbol(base=s[:-4], quote=s[-4:])
        raise ValueError(f"Invalid symbol: {s}")
    base, quote = s.split("/", 1)
    return ParsedSymbol(base=base, quote=quote)

def canonical(symbol: str) -> str:
    p = parse_symbol(symbol)
    return f"{p.base}/{p.quote}"

def to_exchange_symbol(exchange: str, symbol: str) -> str:
    """
    CCXT как правило принимает canonical "BASE/QUOTE".
    Но для специфичных REST позовёмся:
    - gateio REST иногда использует 'BASE_USDT'
    - binance REST часто 'BASEUSDT'
    - okx споты — 'BASE-USDT'
    Эти отличия учитываются там, где идёт вызов прямых REST без CCXT.
    """
    ex = (exchange or "").lower()
    p = parse_symbol(symbol)
    if ex in ("gateio", "gate", "gate-io"):
        return f"{p.base}_{p.quote}"
    if ex in ("binance",):
        return f"{p.base}{p.quote}"
    if ex in ("okx", "okex"):
        return f"{p.base}-{p.quote}"
    # по умолчанию — canonical
    return f"{p.base}/{p.quote}"

def from_exchange_symbol(exchange: str, s: str) -> str:
    """Обратно в canonical 'BASE/QUOTE'."""
    return canonical(s)
