from __future__ import annotations
import time
from typing import Optional
from crypto_ai_bot.utils.http_client import get_http_client

_LAST_MEASURE_TS = 0.0
_LAST_DRIFT_MS = 0

def measure_time_drift() -> int:
    """Measure drift vs public time API. Cached for ~60s by caller if needed."""
    http = get_http_client()
    t0 = time.time()
    data = http.get_json('https://worldtimeapi.org/api/timezone/Etc/UTC', timeout=3.0)
    t1 = time.time()
    server_ms = int((data.get('unixtime', int(t1)))*1000)
    rtt_ms = int((t1 - t0)*1000)
    local_ms = int(t1 * 1000)
    drift = abs(local_ms - server_ms)
    # subtract half RTT as a crude estimate
    drift = max(0, drift - rtt_ms//2)
    global _LAST_MEASURE_TS, _LAST_DRIFT_MS
    _LAST_MEASURE_TS = t1
    _LAST_DRIFT_MS = drift
    return drift

def get_cached_drift_ms(default: int = 0, max_age_sec: int = 60) -> int:
    now = time.time()
    if now - _LAST_MEASURE_TS > max_age_sec:
        try:
            return measure_time_drift()
        except Exception:
            return default
    return _LAST_DRIFT_MS
