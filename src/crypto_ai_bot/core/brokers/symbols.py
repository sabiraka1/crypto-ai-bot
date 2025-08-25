from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sym:
    base: str
    quote: str


def parse_symbol(symbol: str) -> Sym:
    # Внутренний формат всегда "BASE/QUOTE"
    base, quote = symbol.split("/")
    return Sym(base=base.upper(), quote=quote.upper())


def to_exchange_symbol(exchange: str, internal_symbol: str) -> str:
    # Для Gate.io и CCXT — тот же формат `BASE/QUOTE`
    return internal_symbol