# src/crypto_ai_bot/utils/time.py
from __future__ import annotations

import time
from datetime import datetime, timezone

def monotonic_ms() -> int:
    """Монотонные миллисекунды (для измерений/таймеров, не для бизнес-времени)."""
    return int(time.monotonic() * 1000)

def now_ms() -> int:
    """Unix epoch в миллисекундах (UTC)."""
    return int(time.time() * 1000)

def utc_now() -> datetime:
    """Текущее время в UTC как datetime (tz-aware)."""
    return datetime.now(tz=timezone.utc)
