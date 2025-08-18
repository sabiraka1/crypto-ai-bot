# src/crypto_ai_bot/market_context/regime_detector.py
from __future__ import annotations

from typing import Dict, Any


def detect_regime(ind: Dict[str, float]) -> str:
    """
    Простая эвристика:
      - если fear_greed >= 0.6 и btc_dominance в [0.45..0.65] → "risk_on"
      - если fear_greed <= 0.35 или dxy >= 0.66 → "risk_off"
      - иначе "neutral"
    Все значения уже нормированы 0..1.
    """
    fng = float(ind.get("fear_greed", 0.0))
    dom = float(ind.get("btc_dominance", 0.0))
    dxy = float(ind.get("dxy", 0.0))

    if fng >= 0.60 and 0.45 <= dom <= 0.65:
        return "risk_on"
    if fng <= 0.35 or dxy >= 0.66:
        return "risk_off"
    return "neutral"
