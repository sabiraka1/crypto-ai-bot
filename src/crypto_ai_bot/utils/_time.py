# src/crypto_ai_bot/utils/time.py
from __future__ import annotations

import time
from datetime import datetime, timezone


def now_ms() -> int:
    """UTC now в миллисекундах."""
    return int(time.time() * 1000)


def utc_now() -> datetime:
    """Сейчас в UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def ms_to_dt(ms: int) -> datetime:
    """Перевод миллисекунд unix → datetime UTC."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
