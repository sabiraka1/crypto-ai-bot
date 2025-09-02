from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Optional, Any

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class TelegramErrorHandler(logging.Handler):
    """
    Лог-хендлер, который отправляет записи уровня ERROR и выше в Telegram.

    Безопасность:
      - Токен/чат-id читаем из ENV (base64), чтобы не подсвечивать секреты в логах.
      - Отправка идёт в отдельном потоке, чтобы не блокировать рабочие потоки.

    ENV:
      TELEGRAM_BOT_TOKEN_B64
      TELEGRAM_CHAT_ID
      TELEGRAM_BOT_SECRET_B64 (необязательно; если нужен доп.секрет)

      LOG_TG_ERRORS=1  --> включить отправку
      LOG_TG_THROTTLE_SEC=5  --> минимальная задержка между сообщениями (анти-спам)
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
                "TelegramErrorHandler: LOG_TG_ERRORS=1, но TELEGRAM_* не заданы."
            )
        if httpx is None:
            raise RuntimeError("TelegramErrorHandler: httpx не установлен.")

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
                "text": text[:4000],  # TG ограничение
                "disable_web_page_preview": True,
                "parse_mode": "HTML",
            }
            with httpx.Client(timeout=10.0) as client:
                client.post(url, data=payload)
        except Exception:
            # ничего не поднимаем — это хендлер логов
            pass


def _b64env(name: str) -> Optional[str]:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception:
        return None