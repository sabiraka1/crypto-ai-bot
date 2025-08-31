# src/crypto_ai_bot/core/infrastructure/macro/sources/http_dxy.py
from __future__ import annotations

from typing import Optional, Any, Dict, Callable


class DxySource:
    """
    Источник DXY (индекс доллара) по HTTP.
    Ожидаемый формат ответа: {"change_pct": float}
    Если url не задан или ответ некорректен — вернём None.
    """

    def __init__(self, *, http_get_json: Callable[[str], Any], url: Optional[str]) -> None:
        self._get = http_get_json
        self._url = url

    async def change_pct(self) -> Optional[float]:
        if not self._url:
            return None
        try:
            data: Dict[str, Any] = await self._get(self._url)  # должен вернуть dict
            v = data.get("change_pct")
            return float(v) if v is not None else None
        except Exception:
            return None
