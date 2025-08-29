# src/crypto_ai_bot/core/infrastructure/brokers/symbols.py
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
    """Внутренний формат 'BTC/USDT' -> формат биржи (CCXT unified)."""
    ex = (exchange or "").lower()
    bq = parse_symbol(internal_symbol)
    # CCXT для всех поддерживаемых спотовых бирж, включая gateio, ожидает 'BASE/QUOTE'
    return f"{bq.base}/{bq.quote}"

def from_exchange_symbol(exchange: str, ex_symbol: str) -> str:
    """Формат биржи -> внутренний 'BASE/QUOTE'."""
    # Если уже 'BASE/QUOTE' — возвращаем как есть
    if "/" in ex_symbol:
        return ex_symbol
    # fallback: нормализуем в верхний регистр (на случай редких неунифицированных форм)
    return ex_symbol.upper()
