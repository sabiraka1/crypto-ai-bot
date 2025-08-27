from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from crypto_ai_bot.core.infrastructure.settings import Settings


class TelegramNotifier:
    def __init__(self, *, token: Optional[str] = None, chat_id: Optional[str] = None) -> None:
        s = Settings.load()
        if not s.TELEGRAM_ENABLED:
            self._enabled = False
            self._token = None
            self._chat = None
            return
        self._enabled = True
        self._token = token or s.TELEGRAM_BOT_TOKEN
        self._chat = chat_id or s.TELEGRAM_CHAT_ID

    async def send(self, text: str) -> None:
        if not self._enabled or not self._token or not self._chat:
            return
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as cli:
            try:
                await cli.post(url, json={"chat_id": self._chat, "text": text})
            except Exception:
                pass
