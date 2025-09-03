from __future__ import annotations

from typing import Any

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.retry import apost_retry
from crypto_ai_bot.utils.trace import get_cid

_log = get_logger("adapters.telegram")


class TelegramAlerts:
    """
    Ğ˜ÑÑ…Ğ¾Ğ´ÑÑ‰Ğ¸Ğµ ÑƒĞ²ĞµĞ´Ğ¾Ğ¼Ğ»ĞµĞ½Ğ¸Ñ Ğ² Telegram (Bot API).
    """

    def __init__(
        self,
        *,
        bot_token: str = "",
        chat_id: str = "",
        request_timeout_sec: float = 30.0,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        disable_notification: bool = False,
    ) -> None:
        self._token = (bot_token or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._timeout = float(request_timeout_sec)
        self._parse_mode = parse_mode
        self._disable_web_page_preview = bool(disable_web_page_preview)
        self._disable_notification = bool(disable_notification)

    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def _endpoint(self) -> str:
        return f"https://api.telegram.org/bot{self._token}/sendMessage"

    async def send(self, text: str) -> bool:
        """
        Ğ’Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ True, ĞµÑĞ»Ğ¸ HTTP 200 Ğ¸ {"ok":true}.
        Ğ ĞµÑ‚Ñ€Ğ°Ğ¸ Ğ¿Ğ¾ ÑĞµÑ‚Ğ¸ â†’ ÑĞ¼. utils.retry.apost_retry.
        """
        if not self.enabled():
            _log.info("telegram_disabled")
            return False

        cid = get_cid()
        if cid:
            text = f"{text}\n<code>[#CID:{cid}]</code>"

        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": str(text or ""),
            "parse_mode": self._parse_mode,
            "disable_web_page_preview": self._disable_web_page_preview,
            "disable_notification": self._disable_notification,
        }

        try:
            resp = await apost_retry(self._endpoint(), json=payload, timeout=self._timeout)
            if resp.status_code != 200:
                _log.warning("telegram_send_non_200", extra={"status": resp.status_code})
                return False  # noqa: TRY300
            data = resp.json()
            ok = bool(data.get("ok"))
            if not ok:
                _log.warning("telegram_send_not_ok", extra={"response": str(data)})
            return ok
        except Exception:  # noqa: BLE001
            _log.error("telegram_send_exception", exc_info=True)
            return False
