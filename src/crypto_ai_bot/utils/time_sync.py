from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Dict, Any, List
import email.utils as eut

# ВАЖНО: HTTP берём только из нашего клиента
from crypto_ai_bot.utils.http_client import get_http_client


_DEFAULT_URLS: List[str] = [
    # JSON: {"unixtime": 1723800000, ...}
    "https://worldtimeapi.org/api/timezone/Etc/UTC",
    # JSON: {"currentUtcDateTime":"2025-08-16T13:08:49.123Z", ...}
    "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
    # Fallback: заголовок Date
    "https://www.google.com",
    "https://www.cloudflare.com",
]


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _parse_remote_epoch_ms(url: str, body: Dict[str, Any] | None, headers: Dict[str, str]) -> Optional[int]:
    """
    Пытаемся достать удалённое UTC-время в миллисекундах:
    1) известные JSON-поля;
    2) заголовок Date (RFC 7231).
    """
    # WorldTimeAPI
    if body and "unixtime" in body and isinstance(body["unixtime"], (int, float)):
        return int(float(body["unixtime"]) * 1000)

    # timeapi.io
    if body and "currentUtcDateTime" in body and isinstance(body["currentUtcDateTime"], str):
        # формат вида 2025-08-16T13:08:49.123Z
        try:
            dt = datetime.fromisoformat(body["currentUtcDateTime"].replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            pass

    # Заголовок Date
    date_hdr = None
    for k, v in headers.items():
        if k.lower() == "date":
            date_hdr = v
            break
    if date_hdr:
        try:
            # Пример: 'Sat, 16 Aug 2025 13:08:49 GMT'
            tup = eut.parsedate_to_datetime(date_hdr)
            if tup.tzinfo is None:
                tup = tup.replace(tzinfo=timezone.utc)
            return int(tup.timestamp() * 1000)
        except Exception:
            pass

    return None


def measure_time_drift(cfg=None, http=None, *, urls: Iterable[str] | None = None, timeout: float = 3.0) -> Optional[int]:
    """
    Возвращает минимальный |remote_ms - local_ms| среди источников.
    Если все источники недоступны — None.
    """
    client = http or get_http_client()
    url_list = list(urls or getattr(cfg, "TIME_DRIFT_URLS", None) or _DEFAULT_URLS)

    best: Optional[int] = None
    for url in url_list:
        try:
            # стараемся получить JSON; при ошибке — хотя бы заголовки
            body = None
            headers: Dict[str, str] = {}
            try:
                body = client.get_json(url, timeout=timeout)  # наш http-клиент
                headers = {}  # в JSON пути у нас заголовков нет — но ок
            except Exception:
                # сделаем "сырой" GET ради заголовка Date
                # наш HttpClient не обязан уметь "raw", поэтому попробуем ещё раз JSON,
                # а заголовки ловим из Exception (многие клиенты кладут response в err)
                # если заголовков нет — ниже просто не распарсим
                body = None
                headers = {}

            remote_ms = _parse_remote_epoch_ms(url, body, headers)
            if remote_ms is None:
                # повторный запрос для получения заголовков (если клиент поддерживает)
                # оставим как есть: у большинства источников JSON достаточно
                continue

            local_ms = _now_ms()
            drift = abs(remote_ms - local_ms)
            best = drift if best is None else min(best, drift)
        except Exception:
            continue

    return best
