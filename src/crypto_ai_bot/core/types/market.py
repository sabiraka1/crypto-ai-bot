# src/crypto_ai_bot/core/types/market.py
from __future__ import annotations
from typing import TypedDict, Optional

class MarketContext(TypedDict, total=False):
    btc_dominance: Optional[float]
    fear_greed:   Optional[float]
    dxy:          Optional[float]
