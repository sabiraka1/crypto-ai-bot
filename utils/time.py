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
    """UTC timestamp in milliseconds."""
    return int(time.time() * _MS)

def monotonic_ms() -> int:
    """Monotonic clock in milliseconds (not related to wall time)."""
    return int(time.monotonic() * _MS)

def sleep_ms(ms: int) -> None:
    """Sleep for the specified milliseconds (blocking)."""
    if ms <= 0:
        return
    time.sleep(ms / _MS)

def iso_utc(ts_ms: Optional[int] = None) -> str:
    """Return ISO-8601 UTC string for given ms timestamp (or now)."""
    if ts_ms is None:
        ts_ms = now_ms()
    return datetime.fromtimestamp(ts_ms / _MS, tz=timezone.utc).isoformat()

def bucket_ms(ts_ms: Optional[int], window_ms: int) -> int:
    """Floor timestamp to a bucket of size window_ms (in ms).
    If ts_ms is None, current time is used.
    """
    if window_ms <= 0:
        raise ValueError("window_ms must be > 0")
    if ts_ms is None:
        ts_ms = now_ms()
    return (ts_ms // window_ms) * window_ms

def check_sync(remote_now_ms: Optional[Callable[[], int]] = None) -> Optional[int]:
    """Return drift (local_now_ms - remote_now_ms) if provider is given, else None.
    Positive value means local clock is ahead of remote.
    This function is best-effort and must not raise.
    """
    if remote_now_ms is None:
        return None
    try:
        local = now_ms()
        remote = int(remote_now_ms())
        return local - remote
    except Exception:
        return None