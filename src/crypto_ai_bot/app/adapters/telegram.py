from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from ...core.infrastructure.settings import Settings
from ...utils.logging import get_logger

_log = get_logger("adapter.telegram")


class TelegramNotifier:
    def __init__(self, token: Optional[str], chat_id: Optional[str], enabled: bool) -> None:
        self._enabled = bool(enabled and token and chat_id)
        self._token = token
        self._chat_id = chat_id

    async def send(self, text: str) -> None:
        if not self._enabled:
            return
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as cl:
                await cl.post(url, json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"})
        except Exception as exc:
            _log.error("telegram_send_failed", extra={"error": str(exc)})


def build_notifier_from_env(settings: Settings) -> TelegramNotifier:
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    enabled = settings.TELEGRAM_ENABLED
    return TelegramNotifier(token, chat_id, enabled)
