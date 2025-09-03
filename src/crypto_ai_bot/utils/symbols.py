from __future__ import annotations
def canonical(symbol: str) -> str:
    """
    Ѹ с Ѿѳ   ѵс .
    Ѹ: 'btc/usdt'  'BTCUSDT' -> 'BTC/USDT'.
    """
    s = str(symbol or "").strip().upper()
    # Ѹ ѾсѸ    сѰ Ѱѵя,
    #  ѵ, Ѿ с Ѷ юѰ '/'.
    return s
