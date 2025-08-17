# src/crypto_ai_bot/market_context/snapshot.py
from __future__ import annotations
from typing import Any, Dict, Optional

def build_snapshot(broker: Any) -> Dict[str, Optional[float]]:
    """
    Мини-снапшот контекста: индексы/доминации могут быть None, если недоступны.
    Расширять по мере необходимости.
    """
    out: Dict[str, Optional[float]] = {
        "btc_dominance": None,
        "dxy_index": None,
        "fear_greed": None,
        "volatility_1d": None,
    }
    # Здесь можно добавить реальные источники (внешние API) — в paper-режиме оставляем None.
    return out
