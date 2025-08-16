from __future__ import annotations

import time
from typing import Dict, List, Tuple, Optional

from crypto_ai_bot.utils.http_client import get_http_client


_DEFAULT_URLS = [
    "https://worldtimeapi.org/api/timezone/Etc/UTC",
]


def _measure_once(http, url: str, timeout: float) -> Optional[int]:
    t_send = time.time()
    data = http.get_json(url, timeout=timeout)
    t_recv = time.time()

    rtt_ms = int((t_recv - t_send) * 1000)
    half_rtt = rtt_ms // 2

    if "unixtime" in data:
        server_ms = int(data["unixtime"]) * 1000
    else:
        server_ms = int(t_recv * 1000)

    local_ms = int(((t_send + t_recv) / 2) * 1000)
    drift_ms = (server_ms - local_ms) - half_rtt
    return drift_ms


def measure_time_drift(http=None, urls: List[str] | None = None, timeout: float = 2.5) -> Tuple[int, Dict[str, int]]:
    http = http or get_http_client()
    urls = [u for u in (urls or _DEFAULT_URLS) if u]
    samples: Dict[str, int] = {}
    vals: List[int] = []

    for url in urls:
        try:
            d = _measure_once(http, url, timeout=timeout)
            if d is not None:
                samples[url] = d
                vals.append(d)
        except Exception:
            continue

    avg = int(sum(vals) / len(vals)) if vals else 0
    return avg, samples
