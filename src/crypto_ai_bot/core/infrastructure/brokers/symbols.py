from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class SymbolParts:
    base: str
    quote: str

def parse_symbol(symbol: str) -> SymbolParts:
    if "/" not in symbol:
        raise ValueError(f"Invalid symbol format: {symbol!r}. Expected BASE/QUOTE, e.g. BTC/USDT")
    base, quote = symbol.split("/", 1)
    return SymbolParts(base=base.upper(), quote=quote.upper())

def to_exchange_symbol(exchange: str, internal_symbol: str) -> str:
    """Внутренний формат 'BTC/USDT' -> формат биржи."""
    ex = (exchange or "").lower()
    bq = parse_symbol(internal_symbol)
    if ex == "gateio":
        # Gate: BTC_USDT
        return f"{bq.base}_{bq.quote}"
    # По умолчанию многие биржи понимают BASE/QUOTE
    return f"{bq.base}/{bq.quote}"

def from_exchange_symbol(exchange: str, ex_symbol: str) -> str:
    """Формат биржи -> внутренний 'BASE/QUOTE'."""
    ex = (exchange or "").lower()
    if ex == "gateio":
        # Gate: BTC_USDT -> BTC/USDT
        if "_" in ex_symbol:
            base, quote = ex_symbol.split("_", 1)
            return f"{base}/{quote}"
    # По умолчанию оставляем как есть (если уже 'BASE/QUOTE')
    if "/" in ex_symbol:
        return ex_symbol
    # fallback: не ломаемся, но нормализуем в верхний регистр
    return ex_symbol.upper()
