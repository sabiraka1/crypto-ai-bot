from __future__ import annotations

import time
from typing import Sequence, Dict, Any, List

from crypto_ai_bot.utils.http_client import get_http_client

# Базовые публичные источники времени
_DEFAULT_URLS = [
    "http://worldtimeapi.org/api/timezone/Etc/UTC",
    "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
]

_LAST_DRIFT_MS: int = 0


def get_last_drift_ms() -> int:
    return int(_LAST_DRIFT_MS)


def _set_last_drift_ms(v: int) -> None:
    global _LAST_DRIFT_MS
    _LAST_DRIFT_MS = int(v)


def _extract_server_ms(resp: Dict[str, Any]) -> int | None:
    # worldtimeapi.org → "unixtime": seconds
    if "unixtime" in resp:
        return int(resp["unixtime"]) * 1000
    # timeapi.io → "dateTime": ISO; "currentLocalTime" может быть, но берём epoch если есть
    if "epoch" in resp:
        return int(float(resp["epoch"]) * 1000)
    return None


def measure_time_drift(urls: Sequence[str] | None = None, timeout: float = 1.5) -> Dict[str, Any]:
    """
    Делает несколько запросов к публичным API времени,
    оценивает drift через метод половины RTT.
    """
    http = get_http_client()
    urls = [u for u in (urls or _DEFAULT_URLS) if u]

    samples: List[int] = []
    for u in urls:
        t0 = time.time()
        try:
            resp = http.get_json(u, timeout=timeout)
        except Exception:
            continue
        t1 = time.time()

        server_ms = _extract_server_ms(resp)
        if server_ms is None:
            continue

        local_ms = int(((t0 + t1) / 2.0) * 1000.0)
        drift = int(server_ms - local_ms)
        samples.append(drift)

    drift_ms = int(sum(samples) / len(samples)) if samples else 0
    _set_last_drift_ms(drift_ms)
    return {"drift_ms": drift_ms, "samples": samples}
