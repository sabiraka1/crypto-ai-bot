from __future__ import annotations


def canonical(symbol: str) -> str:
    """
    Normalize symbol to canonical format.
    Examples: 'btc/usdt' or 'BTCUSDT' -> 'BTC/USDT'.
    """
    s = str(symbol or "").strip().upper()
    
    # If no slash, try to split common pairs
    if "/" not in s:
        # Common patterns: BTCUSDT -> BTC/USDT
        common_quotes = ["USDT", "USDC", "BUSD", "USD", "BTC", "ETH", "BNB"]
        for quote in common_quotes:
            if s.endswith(quote):
                base = s[:-len(quote)]
                if base:
                    s = f"{base}/{quote}"
                    break
    
    return s