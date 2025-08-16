# utils/time_sync.py
# Real-world time drift measurement via multiple HTTP time sources.
# Uses project HTTP client; no direct 'requests' imports.
from __future__ import annotations

import time
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List

# We expect the caller to pass an instance returned by utils.http_client.get_http_client()
# which exposes get_json(url, timeout=..., headers=...).
# This keeps us compliant with the project's 'HTTP only via utils.http_client' rule.


def _parse_remote_utc_ms(payload: Dict[str, Any]) -> int | None:
    """Extract UTC epoch milliseconds from various common time APIs.
    Supports:
      - worldtimeapi.org: {'unixtime': 1699999999}  (seconds)
      - worldtimeapi.org: {'utc_datetime': '2025-08-16T12:34:56.789+00:00'} (ISO)
      - timeapi.io:      {'currentUtcDateTime': '2025-08-16T12:34:56.789Z'}  (ISO)
      - generic:         {'epoch': 1699999999123} (ms)
    Returns None if unrecognized.
    """
    # epoch (ms)
    if isinstance(payload.get("epoch"), (int, float)):
        val = int(payload["epoch"])
        # Heuristic: if it's too small, maybe it's seconds — normalize to ms.
        return val if val > 10_000_000_000 else val * 1000

    # worldtimeapi: seconds since epoch
    if isinstance(payload.get("unixtime"), (int, float)):
        return int(float(payload["unixtime"]) * 1000)

    # worldtimeapi: ISO in 'utc_datetime'
    iso = payload.get("utc_datetime")
    if isinstance(iso, str):
        try:
            if iso.endswith("Z"):
                iso = iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            pass

    # timeapi.io: ISO in 'currentUtcDateTime'
    iso2 = payload.get("currentUtcDateTime")
    if isinstance(iso2, str):
        try:
            if iso2.endswith("Z"):
                iso2 = iso2.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso2)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            pass

    # Attempt generic 'datetime' or 'dateTime' shapes (ISO)
    for key in ("datetime", "dateTime", "utc_datetime_ms"):
        val = payload.get(key)
        if isinstance(val, str):
            try:
                s = val
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except Exception:
                continue

    return None


def _measure_single_source(http, url: str, timeout: float = 2.0) -> Dict[str, Any]:
    """Measure drift against one source using mid-point technique to reduce RTT bias.
    Returns:
      {'url','ok','drift_ms','error'}
    """
    t0 = time.time() * 1000.0  # ms
    try:
        payload = http.get_json(url, timeout=timeout)
    except Exception as e:
        return {'url': url, 'ok': False, 'drift_ms': None, 'error': f'http_error:{type(e).__name__}:{e}'}

    t1 = time.time() * 1000.0
    client_mid = (t0 + t1) / 2.0

    try:
        remote_ms = _parse_remote_utc_ms(payload)
        if remote_ms is None:
            return {'url': url, 'ok': False, 'drift_ms': None, 'error': 'unrecognized_payload'}
        drift = int(remote_ms - client_mid)
        return {'url': url, 'ok': True, 'drift_ms': drift, 'error': None}
    except Exception as e:
        return {'url': url, 'ok': False, 'drift_ms': None, 'error': f'parse_error:{type(e).__name__}:{e}'}


def measure_time_drift(http,
                       urls: list[str] | None = None,
                       *, timeout: float = 2.0) -> Dict[str, Any]:
    """Measure drift across multiple sources and return a consolidated view.
    Args:
      http: utils.http_client.HttpClient
      urls: list of time endpoints; if None, use two defaults.
      timeout: per-request timeout (seconds).
    Returns:
      {{
        'drift_ms': int | None,                 # median across successful sources
        'per_source': List[{{url, ok, drift_ms, error}}],
        'ok_count': int,
        'total': int
      }}
    """
    if not urls:
        urls = [
            "https://worldtimeapi.org/api/timezone/Etc/UTC",
            "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
        ]

    results = [_measure_single_source(http, u, timeout=timeout) for u in urls]
    ok_drifts = [r["drift_ms"] for r in results if r.get("ok") and isinstance(r.get("drift_ms"), (int, float))]

    agg = {
        "drift_ms": int(median(ok_drifts)) if ok_drifts else None,
        "per_source": results,
        "ok_count": sum(1 for r in results if r.get("ok")),
        "total": len(results),
    }
    return agg
