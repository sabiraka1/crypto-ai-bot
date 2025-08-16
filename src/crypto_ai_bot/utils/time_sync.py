# src/crypto_ai_bot/utils/time_sync.py
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable, Optional

# ожидаем, что в проекте есть наш HttpClient
# (utils/http_client.get_http_client().get_json(url, timeout=...))
# Но здесь принимаем http из внешнего кода, чтобы легко мокать в тестах.

# Дефолтные источники времени (HTTP JSON)
_DEFAULT_TIME_URLS: list[str] = [
    # worldtimeapi: содержит unixtime (секунды) и utc_datetime (ISO)
    "https://worldtimeapi.org/api/timezone/Etc/UTC",
    # timeapi.io: отдаёт ISO в полях, формат может меняться — парсим универсально
    "https://www.timeapi.io/api/Time/current/zone?timeZone=UTC",
    # дополнительный публичный API (резерв; может меняться)
    "https://timeapi.app/now",
]


def _to_unix_ms_from_payload(payload: dict) -> Optional[int]:
    """
    Пытаемся вытащить время сервера в миллисекундах из разных форматов.
    Поддерживаем несколько популярных ключей и ISO-строки.
    """
    if not isinstance(payload, dict):
        return None

    # 1) Прямые числа
    for k in ("unixtime_ms", "epoch_ms", "milliseconds"):
        if k in payload:
            try:
                return int(payload[k])
            except Exception:
                pass

    # 2) unixtime (секунды)
    for k in ("unixtime", "epoch", "seconds"):
        if k in payload:
            try:
                return int(float(payload[k]) * 1000)
            except Exception:
                pass

    # 3) Вложенные структуры, встречающиеся в некоторых API
    # worldtimeapi.org: "unixtime" наверху, но на всякий случай поддержим "utc_datetime"
    for k in ("utc_datetime", "utcDateTime", "datetime", "dateTime", "currentLocalTime", "time"):
        if k in payload:
            val = payload[k]
            if isinstance(val, str):
                for candidate in (val, val.replace("Z", "+00:00")):
                    try:
                        # fromisoformat не ест "Z", поэтому выше заменяем
                        dt = datetime.fromisoformat(candidate)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return int(dt.timestamp() * 1000)
                    except Exception:
                        continue

    # 4) Ничего не нашли
    return None


def measure_time_drift(*, http, urls: Optional[Iterable[str]] = None, timeout: float = 2.0) -> Optional[int]:
    """
    Возвращает оценку расхождения локальных часов с сервером (в миллисекундах).
    Берём медиану по успешно измеренным источникам (с поправкой на половину RTT).

    :param http: инстанс HttpClient (ожидаем .get_json(url, timeout=...))
    :param urls: список URL-ов. Если None/пусто — используем дефолтный список
    :param timeout: таймаут запроса в секундах
    :return: |drift_ms| (int) или None, если ни один источник не удался
    """
    candidates = list(urls or _DEFAULT_TIME_URLS)
    drifts: list[int] = []

    for url in candidates:
        t0 = time.perf_counter()
        local_ms_before = int(time.time() * 1000)
        try:
            payload = http.get_json(url, timeout=timeout)
        except Exception:
            continue
        local_ms_after = int(time.time() * 1000)
        t1 = time.perf_counter()

        rtt_ms = int((t1 - t0) * 1000)
        server_ms = _to_unix_ms_from_payload(payload)
        if server_ms is None:
            continue

        # считаем, что серверное время соответствует середине запроса
        midpoint_local_ms = local_ms_after - (rtt_ms // 2)
        drift_ms = abs(server_ms - midpoint_local_ms)
        drifts.append(drift_ms)

    if not drifts:
        return None

    # медиана — устойчивее к выбросам
    drifts.sort()
    mid = len(drifts) // 2
    if len(drifts) % 2 == 1:
        return int(drifts[mid])
    return int((drifts[mid - 1] + drifts[mid]) / 2)
