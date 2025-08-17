# src/crypto_ai_bot/core/types/trading.py
from __future__ import annotations
from enum import Enum

class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
