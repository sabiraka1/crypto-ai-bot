from __future__ import annotations


def canonical(symbol: str) -> str:
    """
    Сё СЃ СѕСі   СµСЃ .
    Сё: 'btc/usdt'  'BTCUSDT' -> 'BTC/USDT'.
    """
    s = str(symbol or "").strip().upper()
    # Сё СѕСЃСё    СЃС° С°СµСЏ,
    #  Сµ, Сѕ СЃ С¶ СЋС° '/'.
    return s
