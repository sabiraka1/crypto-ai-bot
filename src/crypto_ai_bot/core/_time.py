# src/crypto_ai_bot/core/_time.py
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone


def now_ms() -> int:
    """UTC now в миллисекундах (int). Единая точка времени для всей системы."""
    return int(time.time() * 1000)


def utc_now() -> datetime:
    """Текущий UTC datetime (aware). Удобно для логов/аудита."""
    return datetime.now(timezone.utc)


def monotonic_ms() -> int:
    """Монотонное время в миллисекундах (для измерения длительностей)."""
    return int(time.monotonic() * 1000)


async def sleep_ms(ms: int) -> None:
    """Асинхронный сон в миллисекундах (избегаем time.sleep в async-коде)."""
    await asyncio.sleep(max(0.0, ms) / 1000.0)
