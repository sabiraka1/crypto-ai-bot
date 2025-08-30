from __future__ import annotations

import asyncio
import json
from typing import Optional
from urllib.parse import quote_plus

import aiohttp

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("alerts.telegram")


class TelegramAlerts:
    """
    Лёгкий алёртер в Telegram.
    — Абсолютные импорты (без относительных путей).
    — Безопасные таймауты и логирование неудачных попыток.
    """

    def __init__(self, bot_token: Optional[str], chat_id: Optional[str]) -> None:
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()

    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, text: str) -> bool:
        if not self.enabled():
            return False
        url = (
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            f"?chat_id={quote_plus(self.chat_id)}"
            f"&text={quote_plus(text)}"
            f"&parse_mode=HTML&disable_web_page_preview=true"
        )
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as resp:
                    if resp.status != 200:
                        _log.warning(
                            "telegram_non_200",
                            extra={"status": resp.status, "body": await resp.text()},
                        )
                        return False
                    data = await resp.json()
                    ok = bool(data.get("ok"))
                    if not ok:
                        _log.warning("telegram_bad_response", extra={"data": json.dumps(data)})
                    return ok
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.error("telegram_send_failed", extra={"error": str(exc)})
            return False
