# src/crypto_ai_bot/utils/time_sync.py
from __future__ import annotations

import time
from typing import Any, Iterable, List, Optional


def _now_ms() -> int:
    return int(time.time() * 1000)


def _extract_remote_ts_ms(url: str, data: Any) -> Optional[int]:
    """
    Пытаемся вытащить timestamp из популярных эндпоинтов:
      - worldtimeapi.org: {"unixtime": 1710000000}
      - timeapi.io: {"milliseconds_since_epoch": 1710000000123} ИЛИ "dateTime"
      - произвольные: пробуем первые числовые поля
    """
    # worldtimeapi.org
    try:
        if isinstance(data, dict) and "unixtime" in data:
            sec = float(data["unixtime"])
            return int(sec * 1000)
    except Exception:
        pass

    # timeapi.io
    try:
        if isinstance(data, dict) and "milliseconds" in data:
            # иногда ключ называется "milliseconds" или "milliseconds_since_epoch"
            m = data.get("milliseconds")
            if m is not None:
                return int(float(m))
        if isinstance(data, dict) and "milliseconds_since_epoch" in data:
            return int(float(data["milliseconds_since_epoch"]))
    except Exception:
        pass

    # generic: любой числовой целевой ключ
    try:
        if isinstance(data, dict):
            for k in ("timestamp", "ts", "epoch_ms", "epoch", "time"):
                if k in data:
                    v = float(data[k])
                    return int(v if "ms" in k or v > 10_000_000_000 else v * 1000)
            # fallback: первый числовой
            for v in data.values():
                try:
                    f = float(v)
                    return int(f if f > 10_000_000_000 else f * 1000)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def measure_time_drift(*, cfg: Any = None, http: Any, urls: Optional[Iterable[str]] = None, timeout: float = 1.5) -> Optional[int]:
    """
    Возвращает оценку абсолютного дрейфа часов в миллисекундах (median по источникам).
    Если ни один источник не сработал — возвращает None.
    """
    srcs: List[str] = []
    if urls:
        srcs = [u for u in urls if u]
    elif cfg is not None:
        srcs = [u.strip() for u in getattr(cfg, "TIME_DRIFT_URLS", []) if u and u.strip()]
    if not srcs:
        srcs = [
            "https://worldtimeapi.org/api/timezone/Etc/UTC",
            "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
        ]

    local = _now_ms()
    samples: List[int] = []

    for u in srcs:
        try:
            data = http.get_json(u, timeout=float(timeout))
        except Exception:
            continue
        remote = _extract_remote_ts_ms(u, data)
        if remote is None:
            continue
        drift = abs(int(remote) - int(local))
        samples.append(int(drift))

    if not samples:
        return None
    samples.sort()
    mid = len(samples) // 2
    if len(samples) % 2 == 1:
        return int(samples[mid])
    return int((samples[mid - 1] + samples[mid]) / 2)
