# src/crypto_ai_bot/utils/time_sync.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional

_CACHE: Dict[str, Any] = {"drift_ms": None, "ts": 0, "source": None}


def measure_time_drift(http) -> tuple[int, str]:
    """Запрашиваем эталонное время и считаем смещение (ms) против локального."""
    t0 = int(time.time() * 1000)
    data = http.get_json("https://worldtimeapi.org/api/timezone/Etc/UTC")
    # worldtimeapi возвращает 'unixtime' (сек) и 'utc_datetime'
    server_ms = int(data.get("unixtime", int(time.time())) * 1000)
    t1 = int(time.time() * 1000)
    # половина RTT — грубая коррекция
    rtt = t1 - t0
    drift = (server_ms + rtt // 2) - t1
    return drift, "worldtimeapi"


def ensure_recent_measurement(http, max_age_sec: int = 60) -> None:
    now = int(time.time() * 1000)
    if (_CACHE["ts"] or 0) + max_age_sec * 1000 > now:
        return
    try:
        dms, src = measure_time_drift(http)
        _CACHE.update({"drift_ms": int(dms), "ts": now, "source": src})
    except Exception:
        # не обновляем на ошибке, оставляем старое значение
        pass


def get_cached_drift_ms(default: int = 0) -> int:
    v = _CACHE.get("drift_ms")
    return int(v) if isinstance(v, int) else default
