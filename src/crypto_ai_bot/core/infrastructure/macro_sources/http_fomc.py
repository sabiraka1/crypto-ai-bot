from __future__ import annotations

from typing import Any

import httpx

from crypto_ai_bot.core.application.ports import FomcCalendarPort
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("macro.fomc_http")


class FomcHttp(FomcCalendarPort):
    """
    HTTP-источник календаря FOMC.

    Ожидаемый JSON (гибко):
      {"event_today": true}
      {"today": true} / {"has_event": true}
      {"data": {"event_today": true}}
      [{"event_today": true}, ...]
    """

    def __init__(self, url: str, timeout_sec: float = 5.0) -> None:
        self._url = url
        self._timeout = float(timeout_sec)

    async def event_today(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers={"User-Agent": "crypto-ai-bot/1.0"}) as c:
                r = await c.get(self._url)
                r.raise_for_status()
                data: Any = r.json()
                val = self._parse_boolean_today(data)
                if val is None:
                    _log.debug("fomc_unexpected_payload", extra={"url": self._url, "payload_preview": str(data)[:200]})
                return bool(val)
        except httpx.HTTPStatusError as e:
            _log.warning("fomc_http_status", extra={"url": self._url, "status": e.response.status_code})
        except httpx.RequestError as e:
            _log.warning("fomc_http_request", extra={"url": self._url, "error": str(e)})
        except Exception:
            _log.error("fomc_http_failed", extra={"url": self._url}, exc_info=True)
        return False

    @staticmethod
    def _parse_boolean_today(data: Any) -> bool | None:
        def _coerce(v: Any) -> bool | None:
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                lo = v.strip().lower()
                if lo in {"true", "1", "yes", "y", "on"}:
                    return True
                if lo in {"false", "0", "no", "n", "off"}:
                    return False
            return None

        if isinstance(data, dict):
            for key in ("event_today", "today", "has_event", "is_today", "event"):
                if key in data:
                    return _coerce(data[key])
            if isinstance(data.get("data"), dict):
                return FomcHttp._parse_boolean_today(data["data"])
            return None

        if isinstance(data, list) and data:
            return FomcHttp._parse_boolean_today(data[0])

        return _coerce(data)
