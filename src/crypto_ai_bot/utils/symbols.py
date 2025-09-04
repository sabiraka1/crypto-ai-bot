from __future__ import annotations
from typing import Tuple

_COMMON_QUOTES = {
    "USDT", "USDC", "BUSD", "USD", "EUR", "TRY",
    "BTC", "ETH", "BNB", "FDUSD", "DAI"
}
_ALIASES = {"XBT": "BTC", "XETH": "ETH", "BCC": "BCH"}
_SEPARATORS = ("/", "-", "_", ":")

def _clean(s: str) -> str:
    return "".join(ch for ch in s.strip().upper() if ch.isalnum() or ch in _SEPARATORS)

def _apply_alias(asset: str) -> str:
    return _ALIASES.get(asset, asset)

def split(symbol: str) -> Tuple[str, str]:
    s = _clean(symbol or "")
    if not s:
        return "", ""
    for sep in _SEPARATORS:
        if sep in s:
            base, quote = s.split(sep, 1)
            return _apply_alias(base), _apply_alias(quote)
    for q in sorted(_COMMON_QUOTES, key=len, reverse=True):
        if s.endswith(q) and len(s) > len(q):
            base = s[: -len(q)]
            return _apply_alias(base), _apply_alias(q)
    return _apply_alias(s), ""

def canonical(symbol: str) -> str:
    base, quote = split(symbol)
    return f"{base}/{quote}" if base and quote else base

def is_valid(symbol: str) -> bool:
    base, quote = split(symbol)
    return bool(base and quote and base.isalnum() and quote.isalnum())
