from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Callable, Optional

__all__ = [
    "now_ms",
    "monotonic_ms",
    "sleep_ms",
    "iso_utc",
    "bucket_ms",
    "check_sync",
]

_MS = 1000

def now_ms() -> int:
    return int(time.time() * _MS)

def monotonic_ms() -> int:
    return int(time.monotonic() * _MS)

def sleep_ms(ms: int) -> None:
    if ms <= 0:
        return
    time.sleep(ms / _MS)

def iso_utc(ts_ms: Optional[int] = None) -> str:
    if ts_ms is None:
        ts_ms = now_ms()
    return datetime.fromtimestamp(ts_ms / _MS, tz=timezone.utc).isoformat()

def bucket_ms(ts_ms: Optional[int], window_ms: int) -> int:
    if window_ms <= 0:
        raise ValueError("window_ms must be > 0")
    if ts_ms is None:
        ts_ms = now_ms()
    return (ts_ms // window_ms) * window_ms

def check_sync(remote_now_ms: Optional[Callable[[], int]] = None) -> Optional[int]:
    if remote_now_ms is None:
        return None
    try:
        local = now_ms()
        remote = int(remote_now_ms())
        return local - remote
    except Exception:
        return None