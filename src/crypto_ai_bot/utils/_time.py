# src/crypto_ai_bot/utils/time.py
from __future__ import annotations

import time as _time
from datetime import datetime, timezone

__all__ = [
    "now_ms",
    "monotonic_ms",
    "utc_now",
    "now_ts",
]

def now_ms() -> int:
    """Текущее UTC-время в миллисекундах (на основе time.time())."""
    return int(_time.time() * 1000)

def monotonic_ms() -> int:
    """Монотонный таймер в миллисекундах (для измерения латентностей)."""
    return int(_time.monotonic() * 1000)

def utc_now() -> datetime:
    """Aware datetime в UTC (для штампов в логах/аудите)."""
    return datetime.now(tz=timezone.utc)

def now_ts() -> float:
    """Текущее UTC-время в секундах с плавающей точкой."""
    return _time.time()
