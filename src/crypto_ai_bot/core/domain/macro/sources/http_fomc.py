from __future__ import annotations
from typing import Any
import httpx

from crypto_ai_bot.core.domain.macro.ports import FomcCalendarPort

class FomcHttp(FomcCalendarPort):
    def __init__(self, url: str, timeout_sec: float = 5.0) -> None:
        self._url = url.strip()
        self._timeout = timeout_sec

    async def event_today(self) -> bool:
        if not self._url:
            return False
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(self._url)
            r.raise_for_status()
            data: Any = r.json()
            # ожидаем либо {"event_today": true}, либо {"today": true}
            for k in ("event_today", "today", "fomc_today"):
                if isinstance(data, dict) and isinstance(data.get(k), bool):
                    return bool(data[k])
            return False
