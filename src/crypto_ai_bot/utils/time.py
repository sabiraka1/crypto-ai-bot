from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import asyncio
import time

__all__ = [
    "bucket_ms",
    "check_sync",
    "iso_utc",
    "monotonic_ms",
    "now_ms",
    "sleep_ms",
    "async_sleep_ms",
    "utc_now",
]

_MS = 1000


def now_ms() -> int:
    """UTC-время (эпоха) в миллисекундах."""
    return int(time.time() * _MS)


def monotonic_ms() -> int:
    """Монотонные миллисекунды (не привязаны к системным часам)."""
    return int(time.monotonic() * _MS)


def sleep_ms(ms: int) -> None:
    """Блокирующий сон на заданное количество миллисекунд."""
    if ms <= 0:
        return
    time.sleep(ms / _MS)


async def async_sleep_ms(ms: int) -> None:
    """Неблокирующий сон (asyncio) на заданное количество миллисекунд."""
    if ms <= 0:
        return
    await asyncio.sleep(ms / _MS)


def iso_utc(ts_ms: int | None = None) -> str:
    """ISO-8601 строка в UTC по таймстампу в мс (или текущему времени)."""
    if ts_ms is None:
        ts_ms = now_ms()
    return datetime.fromtimestamp(ts_ms / _MS, tz=UTC).isoformat()


def utc_now() -> datetime:
    """Текущая дата/время в UTC как datetime."""
    return datetime.now(tz=UTC)


def bucket_ms(ts_ms: int | None, window_ms: int) -> int:
    """Округление времени вниз до «корзины» размера window_ms (мс).
    Если ts_ms = None — берём текущее время.
    """
    if window_ms <= 0:
        raise ValueError("window_ms must be > 0")
    if ts_ms is None:
        ts_ms = now_ms()
    return (ts_ms // window_ms) * window_ms


def check_sync(remote_now_ms: Callable[[], int] | None = None) -> int | None:
    """Вернуть дрейф часов (local_now_ms - remote_now_ms), если есть провайдер.
    Положительное значение = локальные часы спешат.
    Best-effort: в случае ошибок вернёт None.
    """
    if remote_now_ms is None:
        return None
    try:
        local = now_ms()
        remote = int(remote_now_ms())
        return local - remote
    except Exception:
        return None
