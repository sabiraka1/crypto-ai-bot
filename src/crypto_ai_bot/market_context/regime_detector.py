# src/crypto_ai_bot/market_context/regime_detector.py
from __future__ import annotations
from typing import List, Literal

def detect_regime(closes: List[float]) -> Literal["bull", "bear", "sideways"]:
    """
    Простейшая эвристика: MA и амплитуда.
    """
    n = len(closes)
    if n < 20:
        return "sideways"
    ma_fast = sum(closes[-10:]) / 10.0
    ma_slow = sum(closes[-20:]) / 20.0
    amp = (max(closes[-20:]) - min(closes[-20:])) / max(1e-9, ma_slow)

    if ma_fast > ma_slow and amp > 0.02:
        return "bull"
    if ma_fast < ma_slow and amp > 0.02:
        return "bear"
    return "sideways"
