# src/crypto_ai_bot/core/brokers/symbols.py
from __future__ import annotations

import re
from typing import Tuple

_PAIR_RE = re.compile(r"^([A-Za-z0-9]+)[/_-]?([A-Za-z0-9]+)$")
_GATE_ALIASES = {"gate", "gateio", "gate.io", "gate_io"}

def split_symbol(s: str) -> Tuple[str, str]:
    if not s:
        raise ValueError("empty symbol")
    s = str(s).strip()
    m = _PAIR_RE.match(s.replace(":", "").replace(".", "").replace(" ", ""))
    if not m:
        raise ValueError(f"invalid symbol: {s}")
    base, quote = m.group(1).upper(), m.group(2).upper()
    return base, quote

def normalize_symbol(s: str) -> str:
    base, quote = split_symbol(s)
    return f"{base}/{quote}"

def to_exchange_symbol(s: str, exchange: str | None = None, *, native: bool = False) -> str:
    base, quote = split_symbol(s)
    ex = (exchange or "").strip().lower()
    if native and ex in _GATE_ALIASES:
        return f"{base}_{quote}"   # нативный Gate
    return f"{base}/{quote}"       # ccxt/unified

def from_exchange_symbol(s: str, exchange: str | None = None) -> str:
    return normalize_symbol(s)

def normalize_timeframe(tf: str | int | float) -> str:
    # ccxt-стиль: '1m','5m','1h','1d','1w'
    import re as _re
    if isinstance(tf, (int, float)):
        n = int(tf)
        if n < 60:
            return f"{n}m"
        if n % 60 == 0 and n < 24 * 60:
            return f"{n // 60}h"
        if n % (24 * 60) == 0:
            return f"{n // (24 * 60)}d"
        return f"{n}m"
    s = str(tf).strip().lower()
    aliases = {
        "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
        "60": "1h", "1h": "1h", "h1": "1h", "1hr": "1h",
        "4h": "4h", "h4": "4h",
        "1d": "1d", "d1": "1d", "24h": "1d",
        "1w": "1w", "w1": "1w",
        "1mth": "1M", "1mo": "1M",
    }
    if s in aliases:
        return aliases[s]
    if _re.match(r"^\d+[mhdwM]$", s):
        return s.upper() if s.endswith("M") else s
    if s.endswith("min"):
        n = int(s[:-3]); return f"{n}m"
    if s.endswith("hour") or s.endswith("h"):
        n = int(_re.sub(r"[^0-9]", "", s)); return f"{n}h"
    if s.endswith("day") or s.endswith("d"):
        n = int(_re.sub(r"[^0-9]", "", s)); return f"{n}d"
    if s.endswith("week") or s.endswith("w"):
        n = int(_re.sub(r"[^0-9]", "", s)); return f"{n}w"
    try:
        n = int(s); return normalize_timeframe(n)
    except Exception:
        return "1h"
