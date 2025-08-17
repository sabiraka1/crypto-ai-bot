# src/crypto_ai_bot/core/types/market.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class OHLCV:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
