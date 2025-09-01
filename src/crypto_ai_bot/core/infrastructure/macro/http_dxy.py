from __future__ import annotations

from typing import Any, Optional

import httpx

from crypto_ai_bot.core.domain.macro.ports import DxyPort
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("macro.http_dxy")


class HttpDxySource(DxyPort):
    """
    Простой HTTP-источник DXY.
    Ожидается JSON вида: {"change_pct": 0.37}
    Если формат другой — подстрой парсер в _parse_change_pct().
    """

    def __init__(self, *, url: str, timeout_sec: float = 5.0) -> None:
        self._url = url
        self._timeout = float(timeout_sec)

    async def change_pct(self) -> Optional[float]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(self._url)
                r.raise_for_status()
                data: Any = r.json()
                return self._parse_change_pct(data)
        except Exception:
            _log.warning("dxy_http_failed", extra={"url": self._url}, exc_info=True)
            return None

    @staticmethod
    def _parse_change_pct(data: Any) -> Optional[float]:
        # Стандартный случай: {"change_pct": 0.12}
        try:
            if isinstance(data, dict) and "change_pct" in data:
                return float(data["change_pct"])
        except Exception:
            return None
        return None
