# src/crypto_ai_bot/utils/time.py
from __future__ import annotations
import time

def now_ms() -> int:
    """UTC now in milliseconds."""
    return int(time.time() * 1000)

def utc_ts() -> float:
    """UTC timestamp in seconds (float)."""
    return time.time()
