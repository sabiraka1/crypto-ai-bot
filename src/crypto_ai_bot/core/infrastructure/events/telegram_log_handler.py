from __future__ import annotations

import base64
import logging
import os
import threading
import time

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class TelegramErrorHandler(logging.Handler):
    """
    ДћвЂєДћВѕДћВі-Г‘вЂ¦ДћВµДћВЅДћВґДћВ»ДћВµГ‘в‚¬, ДћВєДћВѕГ‘вЂљДћВѕГ‘в‚¬Г‘вЂ№ДћВ№ ДћВѕГ‘вЂљДћВїГ‘в‚¬ДћВ°ДћВІДћВ»Г‘ВЏДћВµГ‘вЂљ ДћВ·ДћВ°ДћВїДћВёГ‘ВЃДћВё Г‘Ж’Г‘в‚¬ДћВѕДћВІДћВЅГ‘ВЏ ERROR ДћВё ДћВІГ‘вЂ№Г‘Л†ДћВµ ДћВІ Telegram.

    ДћвЂДћВµДћВ·ДћВѕДћВїДћВ°Г‘ВЃДћВЅДћВѕГ‘ВЃГ‘вЂљГ‘Е’:
      - ДћВўДћВѕДћВєДћВµДћВЅ/Г‘вЂЎДћВ°Г‘вЂљ-id Г‘вЂЎДћВёГ‘вЂљДћВ°ДћВµДћВј ДћВёДћВ· ENV (base64), Г‘вЂЎГ‘вЂљДћВѕДћВ±Г‘вЂ№ ДћВЅДћВµ ДћВїДћВѕДћВґГ‘ВЃДћВІДћВµГ‘вЂЎДћВёДћВІДћВ°Г‘вЂљГ‘Е’ Г‘ВЃДћВµДћВєГ‘в‚¬ДћВµГ‘вЂљГ‘вЂ№ ДћВІ ДћВ»ДћВѕДћВіДћВ°Г‘вЂ¦.
      - ДћВћГ‘вЂљДћВїГ‘в‚¬ДћВ°ДћВІДћВєДћВ° ДћВёДћВґГ‘вЂГ‘вЂљ ДћВІ ДћВѕГ‘вЂљДћВґДћВµДћВ»Г‘Е’ДћВЅДћВѕДћВј ДћВїДћВѕГ‘вЂљДћВѕДћВєДћВµ, Г‘вЂЎГ‘вЂљДћВѕДћВ±Г‘вЂ№ ДћВЅДћВµ ДћВ±ДћВ»ДћВѕДћВєДћВёГ‘в‚¬ДћВѕДћВІДћВ°Г‘вЂљГ‘Е’ Г‘в‚¬ДћВ°ДћВ±ДћВѕГ‘вЂЎДћВёДћВµ ДћВїДћВѕГ‘вЂљДћВѕДћВєДћВё.

    ENV:
      TELEGRAM_BOT_TOKEN_B64
      TELEGRAM_CHAT_ID
      TELEGRAM_BOT_SECRET_B64 (ДћВЅДћВµДћВѕДћВ±Г‘ВЏДћВ·ДћВ°Г‘вЂљДћВµДћВ»Г‘Е’ДћВЅДћВѕ; ДћВµГ‘ВЃДћВ»ДћВё ДћВЅГ‘Ж’ДћВ¶ДћВµДћВЅ ДћВґДћВѕДћВї.Г‘ВЃДћВµДћВєГ‘в‚¬ДћВµГ‘вЂљ)

      LOG_TG_ERRORS=1  --> ДћВІДћВєДћВ»Г‘ВЋГ‘вЂЎДћВёГ‘вЂљГ‘Е’ ДћВѕГ‘вЂљДћВїГ‘в‚¬ДћВ°ДћВІДћВєГ‘Ж’
      LOG_TG_THROTTLE_SEC=5  --> ДћВјДћВёДћВЅДћВёДћВјДћВ°ДћВ»Г‘Е’ДћВЅДћВ°Г‘ВЏ ДћВ·ДћВ°ДћВґДћВµГ‘в‚¬ДћВ¶ДћВєДћВ° ДћВјДћВµДћВ¶ДћВґГ‘Ж’ Г‘ВЃДћВѕДћВѕДћВ±Г‘вЂ°ДћВµДћВЅДћВёГ‘ВЏДћВјДћВё (ДћВ°ДћВЅГ‘вЂљДћВё-Г‘ВЃДћВїДћВ°ДћВј)
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
                "TelegramErrorHandler: LOG_TG_ERRORS=1, ДћВЅДћВѕ TELEGRAM_* ДћВЅДћВµ ДћВ·ДћВ°ДћВґДћВ°ДћВЅГ‘вЂ№."
            )
        if httpx is None:
            raise RuntimeError(
                "TelegramErrorHandler: httpx ДћВЅДћВµ Г‘Ж’Г‘ВЃГ‘вЂљДћВ°ДћВЅДћВѕДћВІДћВ»ДћВµДћВЅ."
            )

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
                "text": text[:4000],  # TG ДћВѕДћВіГ‘в‚¬ДћВ°ДћВЅДћВёГ‘вЂЎДћВµДћВЅДћВёДћВµ
                "disable_web_page_preview": True,
                "parse_mode": "HTML",
            }
            with httpx.Client(timeout=10.0) as client:
                client.post(url, data=payload)
        except Exception:
            # ДћВЅДћВёГ‘вЂЎДћВµДћВіДћВѕ ДћВЅДћВµ ДћВїДћВѕДћВґДћВЅДћВёДћВјДћВ°ДћВµДћВј Гўв‚¬вЂќ Г‘ВЌГ‘вЂљДћВѕ Г‘вЂ¦ДћВµДћВЅДћВґДћВ»ДћВµГ‘в‚¬ ДћВ»ДћВѕДћВіДћВѕДћВІ
            pass


def _b64env(name: str) -> str | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception:
        return None
