from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.http_client import apost  # единый слой HTTP

_log = get_logger("adapters.telegram")


class TelegramAlerts:
    """
    Минимальная асинхронная обёртка над Telegram Bot API.

    Поведение:
      - Если token/chat_id не заданы — объект "выключен" (enabled() == False), send() возвращает False без ошибок.
      - Отправка сообщений HTML-разметкой; предпросмотр ссылок выключен.
      - Ошибки логируем со стеком, но не роняем процесс.
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
        Возвращает True, если получили HTTP 200 + {"ok": true}.
        Ошибки не пробрасываем (best-effort), но логируем со стеком.
        """
        if not self.enabled():
            _log.info("telegram_disabled")
            return False

        payload: Dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": str(text or ""),
            "parse_mode": self._parse_mode,
            "disable_web_page_preview": self._disable_web_page_preview,
            "disable_notification": self._disable_notification,
        }

        try:
            resp = await apost(self._endpoint(), json=payload, timeout=self._timeout)
            if resp.status_code != 200:
                _log.warning(
                    "telegram_send_non_200",
                    extra={"status": resp.status_code, "reason": getattr(resp, "reason_phrase", "")},
                )
                return False
            try:
                data = resp.json()
            except Exception:
                _log.error("telegram_send_invalid_json", exc_info=True)
                return False

            ok = bool(data.get("ok"))
            if not ok:
                _log.warning("telegram_send_not_ok", extra={"response": str(data)})
            return ok
        except Exception:
            _log.error("telegram_send_exception", exc_info=True)
            return False
