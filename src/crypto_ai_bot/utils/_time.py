# src/crypto_ai_bot/utils/time.py
from __future__ import annotations
import time

__all__ = ["now_ms", "mono_ms"]

def now_ms() -> int:
    """UTC now in milliseconds."""
    return int(time.time() * 1000)

def mono_ms() -> int:
    """Monotonic time in milliseconds (для измерения латентностей)."""
    return int(time.monotonic() * 1000)
