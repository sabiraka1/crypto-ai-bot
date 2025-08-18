# src/crypto_ai_bot/core/brokers/symbols.py
from __future__ import annotations
from typing import Tuple, Optional, List

# Часто встречающиеся котируемые валюты
_QUOTE_SET = {
    "USDT", "USD", "USDC", "BUSD", "TUSD", "DAI",
    "BTC", "ETH", "EUR", "TRY", "UAH", "RUB"
}

_SEPARATORS = ("_", "-", "/", ":")


def _split_by_separators(raw: str) -> Optional[Tuple[str, str]]:
    up = raw.strip().upper()
    for sep in _SEPARATORS:
        if sep in up:
            b, q = up.split(sep, 1)
            return b, q
    return None


def _split_by_suffix(raw: str) -> Optional[Tuple[str, str]]:
    up = raw.strip().upper()
    # ищем самый длинный подходящий суффикс (например, USDT раньше USD)
    best = None
    for quote in sorted(_QUOTE_SET, key=len, reverse=True):
        if up.endswith(quote) and len(up) > len(quote):
            base = up[: -len(quote)]
            if base.isalpha():
                best = (base, quote)
                break
    return best


def parse_symbol(raw: str) -> Tuple[str, str]:
    """
    Принимает любую из форм:
      'BTC/USDT', 'BTC_USDT', 'BTC-USDT', 'BTCUSDT', 'btc:usdt'
    Возвращает ('BTC','USDT') или бросает ValueError.
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("symbol must be a non-empty string")
    pair = _split_by_separators(raw) or _split_by_suffix(raw)
    if not pair:
        raise ValueError(f"cannot parse symbol: {raw!r}")
    base, quote = pair
    if not base.isalpha() or not quote.isalpha():
        raise ValueError(f"invalid symbol tokens: {raw!r}")
    return base.upper(), quote.upper()


def to_canonical_symbol(raw: str) -> str:
    """Внутренний канон: 'BASE/QUOTE' (подходит и для CCXT)."""
    b, q = parse_symbol(raw)
    return f"{b}/{q}"


def to_ccxt_symbol(raw: str, exchange: Optional[str] = None) -> str:
    """
    Символ для CCXT — всегда 'BASE/QUOTE' независимо от биржи.
    """
    return to_canonical_symbol(raw)


def to_native_symbol(raw: str, exchange: str) -> str:
    """
    Нативный формат биржи (если когда-нибудь понадобится прямой REST/WSS):
      - gateio:  'BASE_QUOTE'
      - okx:     'BASE-QUOTE'
      - binance/bybit/mexc/kucoin/bitget: 'BASEQUOTE'
      - иначе:   'BASE/QUOTE'
    """
    b, q = parse_symbol(raw)
    ex = (exchange or "").lower()
    if ex == "gateio":
        return f"{b}_{q}"
    if ex == "okx":
        return f"{b}-{q}"
    if ex in {"binance", "bybit", "mexc", "kucoin", "bitget"}:
        return f"{b}{q}"
    return f"{b}/{q}"


def from_native_symbol(native: str, exchange: str) -> str:
    """
    Обратное преобразование из нативного формата биржи в канон 'BASE/QUOTE'.
    """
    b, q = parse_symbol(native)
    return f"{b}/{q}"


def symbol_variants(raw: str) -> List[str]:
    """
    Набор эквивалентных представлений: канон + '_' + '-' + без разделителя.
    Нужен для совместимости со старыми данными в БД.
    """
    b, q = parse_symbol(raw)
    return [f"{b}/{q}", f"{b}_{q}", f"{b}-{q}", f"{b}{q}"]
