# src/crypto_ai_bot/core/infrastructure/macro/sources/http_fomc.py
from __future__ import annotations

from typing import Optional, Any, Dict, Callable


class FomcSource:
    """
    Источник календаря ФРС по HTTP.
    Ожидаемый формат ответа: {"event_today": true|false}
    """

    def __init__(self, *, http_get_json: Callable[[str], Any], url: Optional[str]) -> None:
        self._get = http_get_json
        self._url = url

    async def event_today(self) -> bool:
        if not self._url:
            return False
        try:
            data: Dict[str, Any] = await self._get(self._url)
            v = data.get("event_today")
            return bool(v)
        except Exception:
            return False
