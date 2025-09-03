from __future__ import annotations

import asyncio, time

from typing import Any

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.retry import apost_retry
from crypto_ai_bot.utils.trace import get_cid

_log = get_logger("adapters.telegram")


class TelegramAlerts:
    """Adapter for Telegram (Bot API)."""

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
        С°С° True, СЃ HTTP 200  {"ok":true}.
        С°  СЃСё  СЃ. utils.retry.apost_retry.
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

        success: bool = False
        try:
            resp = await apost_retry(self._endpoint(), json=payload, timeout=self._timeout)
            if resp.status_code != 200:
                _log.warning("telegram_send_non_200", extra={"status": resp.status_code})
            else:
                data = resp.json()
                ok = bool(data.get("ok"))
                if not ok:
                    _log.warning("telegram_send_not_ok", extra={"response": str(data)})
                success = ok
        except Exception:  # noqa: BLE001
            _log.error("telegram_send_exception", exc_info=True)
            success = False
        return success


async def _bucket_acquire(self) -> None:
    async with self._bucket_lock:
        now = time.time()
        elapsed = max(0.0, now - self._bucket_last)
        self._bucket_last = now
        # refill
        self._bucket_tokens = min(5.0, self._bucket_tokens + elapsed * self._bucket_rate)
        if self._bucket_tokens >= 1.0:
            self._bucket_tokens -= 1.0
            return
        # need to wait for next token
        need = 1.0 - self._bucket_tokens
        await asyncio.sleep(need / self._bucket_rate)
        # consume after wait
        self._bucket_tokens = max(0.0, self._bucket_tokens - 1.0)
