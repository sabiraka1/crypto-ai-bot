from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSymbol:
    base: str
    quote: str


def parse_symbol(symbol: str) -> ParsedSymbol:
    if not symbol or "/" not in symbol:
        raise ValueError(f"invalid symbol: {symbol}")
    base, quote = symbol.split("/", 1)
    base = base.strip().upper()
    quote = quote.strip().upper()
    if not base or not quote:
        raise ValueError(f"invalid symbol: {symbol}")
    return ParsedSymbol(base=base, quote=quote)


# Маппинги названий торговых пар под конкретные биржи (если отличаются от CCXT‑формата)
# CCXT нормализует большинство пар к виду BASE/QUOTE, поэтому по умолчанию — identity.
# Здесь оставляем задел, чтобы быстро подхватить особенности биржи без правок по всему коду.
_EXCHANGE_SYMBOL_MAP: dict[str, dict[str, str]] = {
    # Примеры (закомментировано до реальной надобности):
    # "kraken": {"XBT/USDT": "BTC/USDT"},
}


def to_exchange_symbol(exchange: str, internal_symbol: str) -> str:
    ex = (exchange or "").strip().lower()
    # Gate.io через CCXT использует формат BASE/QUOTE — identity
    # Binance/Bybit/OKX в CCXT — тоже BASE/QUOTE
    m = _EXCHANGE_SYMBOL_MAP.get(ex)
    if not m:
        return internal_symbol
    return m.get(internal_symbol, internal_symbol)