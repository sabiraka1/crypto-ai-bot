# src/crypto_ai_bot/core/types/signals.py
from __future__ import annotations
from typing import TypedDict, Any, Optional
from .base import Millis

class Decision(TypedDict, total=False):
    id: str
    ts_ms: Millis
    action: str      # "buy" | "sell" | "hold"
    size: str        # Decimal as str
    score: float
    score_base: float
    score_blended: float
    explain: Any
