from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

# HTTP только через utils/http_client.HttpClient

DEFAULT_URL = "https://worldtimeapi.org/api/timezone/Etc/UTC"

def measure_time_drift(http, *, url: str = DEFAULT_URL, timeout: float = 2.0) -> Dict[str, Any]:
    """
    Измерить рассинхронизацию локальных часов с эталоном по простому NTP-подобному подходу:
      - t0 = now_utc()
      - R  = http GET UTC time
      - t1 = now_utc()
      - latency ≈ (t1 - t0)
      - mid = t0 + latency/2
      - drift_ms = |mid - R|
    Возвращает словарь: {"drift_ms": int, "latency_ms": int, "source": url, "ok": bool}
    В случае ошибки: {"drift_ms": 0, "latency_ms": -1, "source": url, "ok": False, "error": "..."}
    """
    from time import perf_counter
    try:
        t0 = perf_counter()
        local0 = datetime.now(timezone.utc)
        data = http.get_json(url, timeout=timeout)  # должен вернуть json
        local1 = datetime.now(timezone.utc)
        t1 = perf_counter()
        # latency
        lat_ms = int((t1 - t0) * 1000)
        # распарсим удалённое время
        # worldtimeapi отвечает utc_datetime, unixtime
        remote_ts = None
        if isinstance(data, dict):
            try:
                if "unixtime" in data:
                    remote_ts = datetime.fromtimestamp(float(data["unixtime"]), tz=timezone.utc)
                elif "utc_datetime" in data:
                    # iso
                    remote_ts = datetime.fromisoformat(data["utc_datetime"].replace("Z", "+00:00"))
            except Exception:
                remote_ts = None
        if remote_ts is None:
            return {"drift_ms": 0, "latency_ms": lat_ms, "source": url, "ok": False, "error": "bad_time_payload"}
        # mid-point
        mid = local0 + (local1 - local0) / 2
        drift_ms = int(abs((mid - remote_ts).total_seconds()) * 1000)
        return {"drift_ms": drift_ms, "latency_ms": lat_ms, "source": url, "ok": True}
    except Exception as e:
        return {"drift_ms": 0, "latency_ms": -1, "source": url, "ok": False, "error": type(e).__name__}
