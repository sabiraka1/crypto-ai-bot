# src/crypto_ai_bot/utils/time_sync.py
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Optional


WORLD_TIME_API = "https://worldtimeapi.org/api/timezone/Etc/UTC"


async def measure_time_drift(http) -> Optional[float]:
    """
    Возвращает оценку дрейфа системного времени в миллисекундах относительно внешнего источника.
    Если внешний источник недоступен — возвращает None (статус 'unknown' в /health).
    ВАЖНО: внешний HTTP вызов — выполняется через utils.http_client, как и предписано правилами.
    """
    try:
        # http.get_json может быть синхронным; если так — завернём в тред на стороне вызывающего
        data = await _maybe_async_get_json(http, WORLD_TIME_API)
        # worldtimeapi.org возвращает 'unixtime' (секунды) и 'datetime'
        if "unixtime" in data:
            external_ts_ms = float(data["unixtime"]) * 1000.0
        elif "datetime" in data:
            # ISO8601 → ms
            dt = datetime.fromisoformat(data["datetime"].replace("Z", "+00:00"))
            external_ts_ms = dt.timestamp() * 1000.0
        else:
            return None

        local_ts_ms = time.time() * 1000.0
        drift_ms = local_ts_ms - external_ts_ms
        # округлим «красиво»
        return float(int(drift_ms))
    except Exception:
        return None


async def _maybe_async_get_json(http, url: str) -> dict:
    """
    Вспомогательный адаптер: если http.get_json синхронный — исполним в отдельном треде,
    если он async — просто подождём его.
    """
    fn = getattr(http, "get_json", None)
    if fn is None:
        raise RuntimeError("HttpClient has no get_json()")

    if _is_coroutine_function(fn):
        return await fn(url, timeout=5.0, headers={"User-Agent": "crypto-ai-bot/health-probe"})
    else:
        import asyncio
        return await asyncio.to_thread(fn, url, timeout=5.0, headers={"User-Agent": "crypto-ai-bot/health-probe"})


def _is_coroutine_function(func) -> bool:
    import inspect
    return inspect.iscoroutinefunction(func)
