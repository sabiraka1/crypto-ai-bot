# src/crypto_ai_bot/core/infrastructure/macro/sources/http_fomc.py
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class FomcSource:
    """
    Источник календаря ФРС по HTTP.
    Ожидаемый формат ответа: {"event_today": true|false}
    """

    def __init__(self, *, http_get_json: Callable[[str], Any], url: str | None) -> None:
        self._get = http_get_json
        self._url = url

    async def event_today(self) -> bool:
        if not self._url:
            return False
        try:
            data: dict[str, Any] = await self._get(self._url)
            v = data.get("event_today")
            return bool(v)
        except Exception:
            return False
