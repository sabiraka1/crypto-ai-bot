from __future__ import annotations

from typing import Optional
import httpx

from crypto_ai_bot.core.infrastructure.settings import Settings


def get_client(timeout_sec: Optional[float] = None) -> httpx.AsyncClient:
    s = Settings.load()
    to = timeout_sec if timeout_sec is not None else float(s.HTTP_TIMEOUT_SEC)
    return httpx.AsyncClient(timeout=to)
