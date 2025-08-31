from __future__ import annotations
from typing import Any
import httpx

from crypto_ai_bot.core.domain.macro.ports import DxyPort

class DxyHttp(DxyPort):
    def __init__(self, url: str, timeout_sec: float = 5.0) -> None:
        self._url = url.strip()
        self._timeout = timeout_sec

    async def change_pct(self) -> float | None:
        if not self._url:
            return None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(self._url)
            r.raise_for_status()
            data: Any = r.json()
            # Пытаемся вытащить значение гибко
            for k in ("change_pct", "dxy_change_pct", "change", "value"):
                v = data.get(k) if isinstance(data, dict) else None
                if isinstance(v, (int, float)):
                    return float(v)
            return None
