from __future__ import annotations

"""
Нормализация символов между STD-форматом и биржевым.

STD: "BASE/QUOTE"  (например, "BTC/USDT")
Gate.io (spot): "BASE_QUOTE"  (например, "BTC_USDT")

Использование:
    to_exchange_symbol("gateio", "BTC/USDT") -> "BTC_USDT"
    from_exchange_symbol("gateio", "BTC_USDT") -> "BTC/USDT"
"""

from typing import Tuple

__all__ = [
    "parse_symbol",
    "to_exchange_symbol",
    "from_exchange_symbol",
]


def parse_symbol(symbol: str) -> Tuple[str, str]:
    """
    Разбирает произвольный символ в (BASE, QUOTE), максимально безопасно.
    Поддерживает "BTC/USDT", "BTC_USDT", "btc-usdt", "BTCUSDT?" (худший случай).
    """
    s = (symbol or "").strip()
    if not s:
        return "", ""

    # Унифицируем разделители → "/"
    s = s.replace("_", "/").replace("-", "/").upper()

    if "/" in s:
        base, quote = s.split("/", 1)
        return base.strip(), quote.strip()

    # Fallback: пытаемся угадать котировку в конце
    # (Лучше не полагаться на это; используйте явный вид "BASE/QUOTE")
    common_quotes = ("USDT", "USD", "USDC", "BTC", "ETH", "BUSD", "EUR", "TRY")
    for q in common_quotes:
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)], q

    # Ничего умнее — считаем всё base
    return s, ""


def to_exchange_symbol(exchange: str, symbol_std: str) -> str:
    """
    STD → биржевой формат.
    """
    exch = (exchange or "").lower()
    base, quote = parse_symbol(symbol_std)

    if not base or not quote:
        # Возвращаем как есть, чтобы не ломать неожиданные форматы
        return (symbol_std or "").upper()

    if exch == "gateio":
        return f"{base}_{quote}"

    # По умолчанию оставляем STD
    return f"{base}/{quote}"


def from_exchange_symbol(exchange: str, symbol_raw: str) -> str:
    """
    Биржевой → STD формат.
    """
    exch = (exchange or "").lower()
    s = (symbol_raw or "").strip()

    if not s:
        return s

    if exch == "gateio":
        return s.replace("_", "/").upper()

    return s.replace("-", "/").upper()
