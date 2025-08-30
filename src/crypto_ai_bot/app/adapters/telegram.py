from __future__ import annotations

import asyncio
from typing import Optional
import httpx

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("adapters.telegram")


class TelegramAlerts:
    def __init__(self, bot_token: str = "", chat_id: str | int = "", *, timeout_sec: float = 5.0, retries: int = 2):
        self._token = (bot_token or "").strip()
        self._chat = str(chat_id or "").strip()
        self._timeout = float(timeout_sec)
        self._retries = int(retries)
        self._client: Optional[httpx.AsyncClient] = None

    def enabled(self) -> bool:
        return bool(self._token and self._chat)

    async def _client_lazy(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def send(self, text: str) -> bool:
        if not self.enabled():
            return False
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        cli = await self._client_lazy()
        for attempt in range(self._retries + 1):
            try:
                r = await cli.post(url, json=payload)
                if r.status_code == 200 and (r.json().get("ok") is True):
                    return True
                _log.warning("telegram_send_non_200", extra={"status": r.status_code, "body": r.text[:256]})
            except Exception as exc:
                _log.error("telegram_send_exception", extra={"error": str(exc), "attempt": attempt})
            await asyncio.sleep(0.2 * (attempt + 1))
        return False
