# src/crypto_ai_bot/utils/time.py
from __future__ import annotations
import time

def now_ms() -> int:
    """UTC now in milliseconds (int). Single source of truth across the app."""
    return int(time.time() * 1000)

def monotonic_ms() -> int:
    """Monotonic clock in ms (good for latency measurements)."""
    return int(time.monotonic() * 1000)
