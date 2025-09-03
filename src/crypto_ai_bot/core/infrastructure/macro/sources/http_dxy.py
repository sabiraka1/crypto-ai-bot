from __future__ import annotations
from typing import Any

import httpx

from crypto_ai_bot.core.domain.macro.ports import DxyPort
from crypto_ai_bot.utils.logging import get_logger


_log = get_logger("macro.dxy_http")


class DxyHttp(DxyPort):
    """
    HTTP-источник индекса DXY.
    Ожидаемый JSON: {"change_pct": 0.37}
    """

    def __init__(self, url: str, timeout_sec: float = 5.0) -> None:
        self._url = url
        self._timeout = float(timeout_sec)

    async def change_pct(self) -> float | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.get(self._url)
                r.raise_for_status()
                data: Any = r.json()
                return self._parse_change_pct(data)
        except httpx.HTTPStatusError as e:
            _log.warning("dxy_http_status", extra={"url": self._url, "status": e.response.status_code})
        except httpx.RequestError as e:
            _log.warning("dxy_http_request", extra={"url": self._url, "error": str(e)})
        except Exception:
            _log.error("dxy_http_failed", extra={"url": self._url}, exc_info=True)
        return None

    @staticmethod
    def _parse_change_pct(data: Any) -> float | None:
        try:
            if isinstance(data, dict) and "change_pct" in data:
                return float(data["change_pct"])
        except Exception:
            _log.debug("dxy_parse_failed", exc_info=True)
        return None
