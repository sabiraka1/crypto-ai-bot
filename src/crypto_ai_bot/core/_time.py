# src/crypto_ai_bot/core/_time.py
from __future__ import annotations
import time

def now_ms() -> int:
    """Domain-safe timestamp in milliseconds (no infra deps)."""
    return int(time.time() * 1000)
