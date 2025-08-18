# src/crypto_ai_bot/core/types/signals.py
from __future__ import annotations
from typing import TypedDict, NotRequired, Dict, Any


class Explain(TypedDict, total=False):
    source: NotRequired[str]
    reason: NotRequired[str]
    signals: Dict[str, float]
    blocks: list
    weights: Dict[str, float]
    thresholds: Dict[str, float]
    context: Dict[str, Any]


class Decision(TypedDict, total=False):
    id: str
    ts_ms: int
    action: str          # "buy" | "sell" | "hold"
    size: str            # Decimal-as-str
    score: float
    score_base: float
    score_blended: float
    explain: Explain
