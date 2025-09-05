from __future__ import annotations

from typing import Any

import httpx

from crypto_ai_bot.core.application.ports import DxyPort
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("macro.dxy_http")


class DxyHttp(DxyPort):
    """
    HTTP-источник индекса DXY (процентное изменение).

    Ожидаемый JSON (гибко):
      {"change_pct": 0.37}
      {"changePercent": 0.37}
      {"data": {"change_pct": 0.37}}
      [{"change_pct": 0.37}, ...]
    """

    def __init__(self, url: str, timeout_sec: float = 5.0) -> None:
        self._url = url
        self._timeout = float(timeout_sec)

    async def change_pct(self) -> float | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers={"User-Agent": "crypto-ai-bot/1.0"}) as c:
                r = await c.get(self._url)
                r.raise_for_status()
                data: Any = r.json()
                val = self._parse_change_pct(data)
                if val is None:
                    _log.debug("dxy_unexpected_payload", extra={"url": self._url, "payload_preview": str(data)[:200]})
                return val
        except httpx.HTTPStatusError as e:
            _log.warning("dxy_http_status", extra={"url": self._url, "status": e.response.status_code})
        except httpx.RequestError as e:
            _log.warning("dxy_http_request", extra={"url": self._url, "error": str(e)})
        except Exception:
            _log.error("dxy_http_failed", extra={"url": self._url}, exc_info=True)
        return None

    @staticmethod
    def _parse_change_pct(data: Any) -> float | None:
        def _coerce(v: Any) -> float | None:
            try:
                return float(str(v))
            except Exception:
                return None

        if isinstance(data, dict):
            for key in ("change_pct", "changePercent", "pct", "change"):
                if key in data:
                    return _coerce(data[key])
            if isinstance(data.get("data"), dict):
                return DxyHttp._parse_change_pct(data["data"])
            return None

        if isinstance(data, list) and data:
            return DxyHttp._parse_change_pct(data[0])

        return _coerce(data)
