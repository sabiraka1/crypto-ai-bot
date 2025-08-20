# src/crypto_ai_bot/utils/time.py
from __future__ import annotations

import time as _time
from datetime import datetime, timezone

__all__ = ["now_ms", "monotonic_ms", "utc_now", "now_ts"]

def now_ms() -> int:
    """UTC-время в миллисекундах."""
    return int(_time.time() * 1000)

def monotonic_ms() -> int:
    """Монотонный таймер в миллисекундах (для latency/таймаутов)."""
    return int(_time.monotonic() * 1000)

def utc_now() -> datetime:
    """Aware datetime (UTC)."""
    return datetime.now(tz=timezone.utc)

def now_ts() -> float:
    """UTC-время в секундах с плавающей точкой."""
    return _time.time()
