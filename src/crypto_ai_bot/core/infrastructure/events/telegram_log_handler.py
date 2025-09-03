from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Optional

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class TelegramErrorHandler(logging.Handler):
    """
    Ğ›Ğ¾Ğ³-Ñ…ĞµĞ½Ğ´Ğ»ĞµÑ€, ĞºĞ¾Ñ‚Ğ¾Ñ€Ñ‹Ğ¹ Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²Ğ»ÑĞµÑ‚ Ğ·Ğ°Ğ¿Ğ¸ÑĞ¸ ÑƒÑ€Ğ¾Ğ²Ğ½Ñ ERROR Ğ¸ Ğ²Ñ‹ÑˆĞµ Ğ² Telegram.

    Ğ‘ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ğ¾ÑÑ‚ÑŒ:
      - Ğ¢Ğ¾ĞºĞµĞ½/Ñ‡Ğ°Ñ‚-id Ñ‡Ğ¸Ñ‚Ğ°ĞµĞ¼ Ğ¸Ğ· ENV (base64), Ñ‡Ñ‚Ğ¾Ğ±Ñ‹ Ğ½Ğµ Ğ¿Ğ¾Ğ´ÑĞ²ĞµÑ‡Ğ¸Ğ²Ğ°Ñ‚ÑŒ ÑĞµĞºÑ€ĞµÑ‚Ñ‹ Ğ² Ğ»Ğ¾Ğ³Ğ°Ñ….
      - ĞÑ‚Ğ¿Ñ€Ğ°Ğ²ĞºĞ° Ğ¸Ğ´Ñ‘Ñ‚ Ğ² Ğ¾Ñ‚Ğ´ĞµĞ»ÑŒĞ½Ğ¾Ğ¼ Ğ¿Ğ¾Ñ‚Ğ¾ĞºĞµ, Ñ‡Ñ‚Ğ¾Ğ±Ñ‹ Ğ½Ğµ Ğ±Ğ»Ğ¾ĞºĞ¸Ñ€Ğ¾Ğ²Ğ°Ñ‚ÑŒ Ñ€Ğ°Ğ±Ğ¾Ñ‡Ğ¸Ğµ Ğ¿Ğ¾Ñ‚Ğ¾ĞºĞ¸.

    ENV:
      TELEGRAM_BOT_TOKEN_B64
      TELEGRAM_CHAT_ID
      TELEGRAM_BOT_SECRET_B64 (Ğ½ĞµĞ¾Ğ±ÑĞ·Ğ°Ñ‚ĞµĞ»ÑŒĞ½Ğ¾; ĞµÑĞ»Ğ¸ Ğ½ÑƒĞ¶ĞµĞ½ Ğ´Ğ¾Ğ¿.ÑĞµĞºÑ€ĞµÑ‚)

      LOG_TG_ERRORS=1  --> Ğ²ĞºĞ»ÑÑ‡Ğ¸Ñ‚ÑŒ Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²ĞºÑƒ
      LOG_TG_THROTTLE_SEC=5  --> Ğ¼Ğ¸Ğ½Ğ¸Ğ¼Ğ°Ğ»ÑŒĞ½Ğ°Ñ Ğ·Ğ°Ğ´ĞµÑ€Ğ¶ĞºĞ° Ğ¼ĞµĞ¶Ğ´Ñƒ ÑĞ¾Ğ¾Ğ±Ñ‰ĞµĞ½Ğ¸ÑĞ¼Ğ¸ (Ğ°Ğ½Ñ‚Ğ¸-ÑĞ¿Ğ°Ğ¼)
    """

    api_url_template = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, level: int = logging.ERROR) -> None:
        super().__init__(level=level)
        self._token = _b64env("TELEGRAM_BOT_TOKEN_B64")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self._enabled = os.getenv("LOG_TG_ERRORS", "0") == "1"
        self._throttle_sec = float(os.getenv("LOG_TG_THROTTLE_SEC", "5"))
        self._last_sent_at = 0.0
        self._lock = threading.Lock()

        if not self._enabled:
            return
        if not self._token or not self._chat_id:
            raise RuntimeError(
                "TelegramErrorHandler: LOG_TG_ERRORS=1, Ğ½Ğ¾ TELEGRAM_* Ğ½Ğµ Ğ·Ğ°Ğ´Ğ°Ğ½Ñ‹."
            )
        if httpx is None:
            raise RuntimeError("TelegramErrorHandler: httpx Ğ½Ğµ ÑƒÑÑ‚Ğ°Ğ½Ğ¾Ğ²Ğ»ĞµĞ½.")

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover (I/O)
        if not self._enabled:
            return

        try:
            msg = self.format(record)
        except Exception:
            msg = f"[log format error] {record.getMessage()}"

        now = time.time()
        with self._lock:
            if now - self._last_sent_at < self._throttle_sec:
                return
            self._last_sent_at = now

        thread = threading.Thread(target=self._send, args=(msg,), daemon=True)
        thread.start()

    def _send(self, text: str) -> None:  # pragma: no cover (I/O)
        try:
            url = self.api_url_template.format(token=self._token)
            payload = {
                "chat_id": self._chat_id,
                "text": text[:4000],  # TG Ğ¾Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ‡ĞµĞ½Ğ¸Ğµ
                "disable_web_page_preview": True,
                "parse_mode": "HTML",
            }
            with httpx.Client(timeout=10.0) as client:
                client.post(url, data=payload)
        except Exception:
            # Ğ½Ğ¸Ñ‡ĞµĞ³Ğ¾ Ğ½Ğµ Ğ¿Ğ¾Ğ´Ğ½Ğ¸Ğ¼Ğ°ĞµĞ¼ â€” ÑÑ‚Ğ¾ Ñ…ĞµĞ½Ğ´Ğ»ĞµÑ€ Ğ»Ğ¾Ğ³Ğ¾Ğ²
            pass


def _b64env(name: str) -> Optional[str]:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception:
        return None