from __future__ import annotations
import time as _time
import asyncio
from typing import Any


def now_ms() -> int:
    """UTC timestamp в миллисекундах."""
    return int(_time.time() * 1000)


def monotonic_ms() -> int:
    """Монотонное время (не зависит от системных сдвигов), в миллисекундах."""
    return int(_time.monotonic() * 1000)


async def _maybe_call_async(fn: Any) -> int:
    if asyncio.iscoroutine(fn):
        return int(await fn)
    if callable(fn):
        res = fn()
        if asyncio.iscoroutine(res):
            return int(await res)
        return int(res)
    return int(fn)


async def check_sync(broker: Any) -> int:
    """Возвращает расхождение времени (локальное now_ms - удалённое), мс.
    Ожидается, что у брокера есть `fetch_server_time_ms()`/`server_time_ms`/`fetch_time_ms()` (sync или async).
    Если источник недоступен — возвращает 0, не падает.
    """
    candidates: list[Any] = []
    # Сбор возможных источников времени без жёстких импортов/зависимостей
    for name in ("fetch_server_time_ms", "fetch_time_ms", "server_time_ms"):
        if hasattr(broker, name):
            attr = getattr(broker, name)
            candidates.append(attr if callable(attr) else int(attr))
    if not candidates:
        return 0
    try:
        remote_ms = await _maybe_call_async(candidates[0])
        return now_ms() - int(remote_ms)
    except Exception:
        return 0