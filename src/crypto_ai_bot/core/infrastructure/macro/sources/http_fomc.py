from __future__ import annotations

from typing import Any
import httpx

from crypto_ai_bot.core.domain.macro.ports import FomcCalendarPort
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("macro.fomc_http")


class FomcHttp(FomcCalendarPort):
    """HTTP-Ğ¸ÑÑ‚Ğ¾Ñ‡Ğ½Ğ¸Ğº FOMC ĞºĞ°Ğ»ĞµĞ½Ğ´Ğ°Ñ€Ñ. JSON: {"event_today": true}"""
    def __init__(self, url: str, timeout_sec: float = 5.0) -> None:
        self._url = url
        self._timeout = float(timeout_sec)

    async def event_today(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.get(self._url)
                r.raise_for_status()
                data: Any = r.json()
                if isinstance(data, dict) and "event_today" in data:
                    return bool(data["event_today"])
        except Exception:
            _log.warning("fomc_http_failed", extra={"url": self._url}, exc_info=True)
        return False
