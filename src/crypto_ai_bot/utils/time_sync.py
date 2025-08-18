# src/crypto_ai_bot/utils/time_sync.py
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional, Tuple

# Публичный API v2 (по спецификации): возвращаем кортеж (ok, drift_ms)
def check_time_sync_status(
    cfg: Any,
    http: Any,
    *,
    urls: Optional[Iterable[str]] = None,
    timeout: float = 1.5,
    limit_ms: Optional[int] = None,
) -> Tuple[bool, Optional[int], Dict[str, Any]]:
    """
    Возвращает:
      ok: bool — дрейф в пределах лимита (или None → unknown → ok=True мягко)
      drift_ms: |server_time - local_time| (ms) или None, если не смогли измерить
      details: вспомогательные поля (urls, used, errors)
    """
    urls = list(urls or []) or [
        "https://worldtimeapi.org/api/timezone/Etc/UTC",
        "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
        # как запасной вариант — HEAD с Date:
        "https://www.cloudflare.com",
        "https://www.google.com",
    ]
    lim = int(limit_ms if limit_ms is not None else int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000)))

    errors: Dict[str, str] = {}
    best: Optional[float] = None
    used: Optional[str] = None

    # Ожидаемый интерфейс http-клиента: get_json(url, timeout) / get_text / head
    for u in urls:
        t0 = time.time()
        try:
            server_ts = _extract_server_epoch_ms(http, u, timeout=timeout)
            if server_ts is None:
                continue
            # t0 приблизительно локальное время отправки — достаточно для грубой оценки
            local_ms = int(t0 * 1000)
            drift = abs(int(server_ts) - local_ms)
            if best is None or drift < best:
                best = drift
                used = u
        except Exception as e:
            errors[u] = f"{type(e).__name__}: {e}"

    if best is None:
        return True, None, {"limit_ms": lim, "urls": urls, "used": used, "errors": errors, "status": "unknown"}

    ok = best <= lim
    return ok, int(best), {"limit_ms": lim, "urls": urls, "used": used, "errors": errors, "status": "measured"}


def _extract_server_epoch_ms(http: Any, url: str, *, timeout: float) -> Optional[int]:
    """
    Пытаемся получить серверное UTC-время в миллисекундах.
    Поддерживаем 3 формы:
      1) JSON с ключами 'unixtime' (сек) / 'unixtime_ms' (мс) / 'datetime' (ISO)
      2) Заголовок Date из HEAD/GET
      3) Падение → None
    """
    # 1) попробуем JSON
    try:
        if hasattr(http, "get_json"):
            resp = http.get_json(url, timeout=timeout)  # type: ignore
            if isinstance(resp, dict):
                if "unixtime_ms" in resp:
                    return int(resp["unixtime_ms"])
                if "unixtime" in resp:
                    return int(float(resp["unixtime"]) * 1000.0)
                # worldtimeapi: {"unixtime": 1712345678}
                if "datetime" in resp:
                    # ISO «YYYY-MM-DDTHH:MM:SS.mmmZ»
                    import datetime
                    iso = str(resp["datetime"])
                    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
                    return int(dt.timestamp() * 1000.0)
    except Exception:
        pass

    # 2) заголовок Date
    try:
        # предпочтительно HEAD
        if hasattr(http, "head"):
            r = http.head(url, timeout=timeout)  # type: ignore
            headers = getattr(r, "headers", None) or getattr(r, "Headers", None) or {}
        else:
            if hasattr(http, "get"):
                r = http.get(url, timeout=timeout)  # type: ignore
                headers = getattr(r, "headers", None) or {}
            else:
                headers = {}
        datev = None
        for k, v in headers.items():
            if str(k).lower() == "date":
                datev = v
                break
        if datev:
            import email.utils as eut
            import calendar, time as _t
            ts = eut.parsedate(datev)  # type: ignore
            if ts:
                # gmttime → epoch sec
                sec = calendar.timegm(ts)
                return int(sec * 1000.0)
    except Exception:
        pass

    return None


# v1-совместимость (как было в проекте):
def measure_time_drift(cfg: Any, http: Any, *, urls=None, timeout: float = 1.5) -> Optional[int]:
    """
    Старый API — возвращает только |drift_ms| или None. Сохраняем для совместимости.
    """
    ok, drift, _ = check_time_sync_status(cfg, http, urls=urls, timeout=timeout)
    return drift
