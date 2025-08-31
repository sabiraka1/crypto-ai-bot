# src/crypto_ai_bot/core/infrastructure/macro/sources/http_btc_dominance.py
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class BtcDominanceSource:
    """
    Источник BTC.D (доминация BTC) по HTTP.
    Ожидаемый формат ответа: {"change_pct": float}
    """

    def __init__(self, *, http_get_json: Callable[[str], Any], url: str | None) -> None:
        self._get = http_get_json
        self._url = url

    async def change_pct(self) -> float | None:
        if not self._url:
            return None
        try:
            data: dict[str, Any] = await self._get(self._url)
            v = data.get("change_pct")
            return float(v) if v is not None else None
        except Exception:
            return None
