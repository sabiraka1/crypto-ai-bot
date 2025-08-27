from __future__ import annotations

from typing import Optional
import httpx
import os


def get_client(timeout_sec: Optional[float] = None) -> httpx.AsyncClient:
    # Читаем таймаут из ENV напрямую, не нарушая слои
    default_timeout = float(os.getenv("HTTP_TIMEOUT_SEC", "30"))
    to = timeout_sec if timeout_sec is not None else default_timeout
    return httpx.AsyncClient(timeout=to)