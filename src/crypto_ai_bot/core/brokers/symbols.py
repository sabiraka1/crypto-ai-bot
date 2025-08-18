# src/crypto_ai_bot/core/brokers/symbols.py
from __future__ import annotations
from typing import Optional, List, Tuple

# --- timeframes ---
_TF_ALIASES = {
    "1s": "1s", "5s": "5s", "15s": "15s",
    "1m": "1m", "1min": "1m", "60s": "1m",
    "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "60m": "1h", "1hour": "1h",
    "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h",
    "1d": "1d", "24h": "1d", "1day": "1d",
    "1w": "1w", "1week": "1w",
    "1mth": "1M", "1mon": "1M", "1M": "1M",
}

COMMON_QUOTES = (
    "USDT","USD","USDC","BUSD","FDUSD","BTC","ETH",
    "EUR","GBP","JPY","TRY","AUD","RUB","BNB","TUSD",
)

def _split_base_quote(raw: str) -> Tuple[str, str]:
    s = str(raw).strip().upper()
    if not s:
        return "BTC", "USDT"

    # remove derivatives settle suffix (e.g. BTC/USDT:USDT)
    if ":" in s:
        s = s.split(":", 1)[0]

    for sep in ("/", "_", "-", " "):
        if sep in s:
            base, quote = s.split(sep, 1)
            return base or "BTC", quote or "USDT"

    # joined like BTCUSDT -> split by longest matching quote suffix
    for q in sorted(COMMON_QUOTES, key=len, reverse=True):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)], q

    # fallback
    return s, "USDT"

def to_canonical_symbol(raw: str) -> str:
    base, quote = _split_base_quote(raw)
    return f"{base}/{quote}"

def ensure_spot_ccxt_symbol(raw: str) -> str:
    # CCXT canonical BASE/QUOTE for spot
    return to_canonical_symbol(raw)

def to_ccxt_symbol(raw: str, exchange: Optional[str] = None) -> str:
    # spot-only: always canonical
    return ensure_spot_ccxt_symbol(raw)

def normalize_symbol(s: str) -> str:
    return ensure_spot_ccxt_symbol(s)

def normalize_timeframe(tf: str, default: str = "1h") -> str:
    key = (tf or "").strip().lower()
    return _TF_ALIASES.get(key, default)

def symbol_variants(raw: str) -> List[str]:
    """Варианты записи символа, чтобы смотреть в БД/репозиториях."""
    base, quote = _split_base_quote(raw)
    canon = f"{base}/{quote}"
    return [canon, f"{base}{quote}", f"{base}_{quote}", f"{base}-{quote}"]
