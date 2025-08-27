from __future__ import annotations

from typing import Optional
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("telegram")

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token.strip()
        self._chat_id = chat_id.strip()

    async def send(self, text: str) -> None:
        if not self._token or not self._chat_id:
            _log.info("telegram_disabled")
            return
        try:
            import httpx  # lightweight; если нет — можно заменить на aiohttp
        except Exception:
            _log.warning("telegram_http_client_missing")
            return
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as cli:
            try:
                r = await cli.post(url, json={"chat_id": self._chat_id, "text": text})
                if r.status_code >= 300:
                    _log.warning("telegram_send_failed", extra={"status": r.status_code, "body": r.text})
            except Exception as exc:
                _log.error("telegram_send_error", extra={"error": str(exc)})

def from_settings(settings: Optional[Settings] = None) -> TelegramNotifier:
    s = settings or Settings.load()
    token = getattr(s, "API_TOKEN", "") or ""     # уже хранится в Settings
    chat = getattr(s, "TELEGRAM_CHAT_ID", "") if hasattr(s, "TELEGRAM_CHAT_ID") else ""
    return TelegramNotifier(token=token, chat_id=chat)
