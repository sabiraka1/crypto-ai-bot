from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import time

__all__ = [
    "bucket_ms",
    "check_sync",
    "iso_utc",
    "monotonic_ms",
    "now_ms",
    "sleep_ms",
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


def iso_utc(ts_ms: int | None = None) -> str:
    """Return ISO-8601 UTC string for given ms timestamp (or now)."""
    if ts_ms is None:
        ts_ms = now_ms()
    return datetime.fromtimestamp(ts_ms / _MS, tz=UTC).isoformat()


def bucket_ms(ts_ms: int | None, window_ms: int) -> int:
    """Floor timestamp to a bucket of size window_ms (in ms).
    If ts_ms is None, current time is used.
    """
    if window_ms <= 0:
        raise ValueError("window_ms must be > 0")
    if ts_ms is None:
        ts_ms = now_ms()
    return (ts_ms // window_ms) * window_ms


def check_sync(remote_now_ms: Callable[[], int] | None = None) -> int | None:
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
