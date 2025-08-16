# src/crypto_ai_bot/core/brokers/symbols.py
from __future__ import annotations

import re
from typing import Tuple

# Поддерживаемые таймфреймы в нормализованном виде (для проекта)
ALLOWED_TF = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}

# Отображение алиасов → нормализованный tf
TF_ALIASES = {
    "1min": "1m", "01m": "1m", "1M": "1m",
    "3min": "3m", "03m": "3m",
    "5min": "5m", "05m": "5m", "5M": "5m",
    "15min": "15m", "15M": "15m",
    "30min": "30m", "30M": "30m",
    "60min": "1h", "1h": "1h", "1H": "1h", "H1": "1h",
    "2h": "2h", "2H": "2h", "H2": "2h",
    "4h": "4h", "4H": "4h", "H4": "4h",
    "6h": "6h", "6H": "6h", "H6": "6h",
    "12h": "12h", "12H": "12h", "H12": "12h",
    "1d": "1d", "1D": "1d", "D1": "1d",
}

# Для распознавания слитных тикеров вроде BTCUSDT
KNOWN_QUOTES = ("USDT", "USD", "USDC", "BUSD", "BTC", "ETH")


def split_symbol(symbol: str) -> Tuple[str, str]:
    """
    Разбивает строку символа на (BASE, QUOTE).
    Поддержка форматов: 'BTC/USDT', 'btc-usdt', 'BTCUSDT', 'btc_usdt'.
    """
    s = symbol.strip().upper().replace(" ", "")
    # явные разделители
    for sep in ("/", "-", "_", ":"):
        if sep in s:
            base, quote = s.split(sep, 1)
            return base, quote
    # без разделителя: пытаемся по известным квотам
    for q in KNOWN_QUOTES:
        if s.endswith(q):
            base = s[: -len(q)]
            if base:  # не пустой
                return base, q
    # last resort — регулярка буквенных блоков
    m = re.match(r"^([A-Z]+)([A-Z]+)$", s)
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"Cannot parse symbol: {symbol!r}")


def join_symbol(base: str, quote: str) -> str:
    return f"{base.upper()}/{quote.upper()}"


def normalize_symbol(symbol: str, exchange: str = "binance") -> str:
    """
    Нормализует во внутренний формат проекта: 'BASE/QUOTE'.
    Пример: 'btcusdt' → 'BTC/USDT', 'ETH-USDC' → 'ETH/USDC'
    """
    base, quote = split_symbol(symbol)
    return join_symbol(base, quote)


def normalize_timeframe(tf: str, exchange: str = "binance") -> str:
    """
    Приводит таймфрейм к внутреннему виду (строка из ALLOWED_TF).
    Пример: '5min' → '5m', 'H1' → '1h'
    """
    key = tf.strip()
    # Сначала прямой хит
    if key in ALLOWED_TF:
        return key
    # Алиасы
    norm = TF_ALIASES.get(key) or TF_ALIASES.get(key.lower())
    if norm and norm in ALLOWED_TF:
        return norm
    # Попытка упростить (например, '5' → '5m')
    if re.fullmatch(r"\d+", key):
        cand = f"{key}m"
        if cand in ALLOWED_TF:
            return cand
    raise ValueError(f"Unsupported timeframe: {tf!r}")


def to_exchange_symbol(symbol: str, exchange: str = "binance") -> str:
    """
    Преобразует нормализованный 'BASE/QUOTE' в формат конкретной биржи (если нужно).
    Для CCXT Binance формат остаётся 'BASE/QUOTE'.
    Для REST-эндпоинтов без CCXT можно вернуть 'BASEQUOTE' (например, 'BTCUSDT').
    """
    base, quote = split_symbol(symbol)
    ex = (exchange or "binance").lower()
    if ex in {"binance", "bybit", "okx"}:
        return f"{base}/{quote}"  # CCXT-совместимо
    # По умолчанию — слитно
    return f"{base}{quote}"
