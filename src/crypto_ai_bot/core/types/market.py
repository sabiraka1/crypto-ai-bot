# src/crypto_ai_bot/core/types/market.py
from __future__ import annotations
from typing import TypedDict, NotRequired, List, Dict, Any


class OHLCV(TypedDict):
    ts_ms: float
    open: float
    high: float
    low: float
    close: float
    volume: NotRequired[float]


class MarketContext(TypedDict, total=False):
    # «Снимок» внешнего макроконтекста (используется в /context и /status/extended)
    ts_ms: int
    sources: Dict[str, Any]
    indicators: Dict[str, float]        # ключи: btc_dominance, fear_greed, dxy
    weights: Dict[str, float]           # веса источников (из Settings)
    composite: float                    # агрегированный счёт (0..1)
    regime: str                         # "risk_on" | "risk_off" | "neutral"
