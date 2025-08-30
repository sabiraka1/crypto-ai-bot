from __future__ import annotations

def canonical(symbol: str) -> str:
    """
    Единая нормализация символов:
    - 'btc_usdt' → 'BTC/USDT'
    - 'BTC/USDT' → 'BTC/USDT'
    - 'BtC_uSdT' → 'BTC/USDT'
    """
    s = (symbol or "").strip()
    if not s:
        return s
    if "_" in s and "/" not in s:
        b, q = s.split("_", 1)
        return f"{b.upper()}/{q.upper()}"
    if "/" in s:
        b, q = s.split("/", 1)
        return f"{b.upper()}/{q.upper()}"
    # последний случай: просто вернуть как есть (например, уже каноничное имя биржи)
    return s.upper()
