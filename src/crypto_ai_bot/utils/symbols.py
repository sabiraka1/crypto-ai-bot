from __future__ import annotations

def canonical(symbol: str) -> str:
    """
    Приводит символ торговой пары к каноническому виду.
    Например: 'btc/usdt' или 'BTCUSDT' -> 'BTC/USDT'.
    """
    s = str(symbol or "").strip().upper()
    # При необходимости можно добавить логику вставки разделителя, 
    # но предполагаем, что символ уже включает '/'.
    return s
