# src/crypto_ai_bot/core/types/signals.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class SignalScore:
    score: float      # [0..1]
    action: str       # "buy"|"sell"|"hold"
    confidence: float # [0..1]
