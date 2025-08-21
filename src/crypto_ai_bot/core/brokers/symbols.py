from __future__ import annotations


def to_exchange_symbol(exchange: str, symbol: str) -> str:
    """Нормализация под биржу. Gate.io: BTC/USDT → BTC_USDT."""
    if exchange.lower() in {"gate", "gateio", "gate.io"}:
        return symbol.replace("/", "_").upper()
    return symbol.upper()


def from_exchange_symbol(exchange: str, raw: str) -> str:
    """Обратная нормализация. Gate.io: BTC_USDT → BTC/USDT."""
    if exchange.lower() in {"gate", "gateio", "gate.io"}:
        return raw.replace("_", "/").upper()
    return raw.upper()


def parse_symbol(symbol: str) -> tuple[str, str]:
    """Парсит "AAA/BBB" → ("AAA", "BBB"). Допускает "AAA_BBB" и "AAA-BBB" как синонимы."""
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
    elif "_" in symbol:
        base, quote = symbol.split("_", 1)
    elif "-" in symbol:
        base, quote = symbol.split("-", 1)
    else:
        raise ValueError(f"Некорректный символ: {symbol}")
    return base.upper(), quote.upper()