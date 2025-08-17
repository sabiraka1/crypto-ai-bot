# src/crypto_ai_bot/utils/alerts.py
from __future__ import annotations

import time
from typing import Optional, Dict, Any


class AlertState:
    """
    Мини-хранилище состояний алертов (тайминги, последние значения).
    Не хранит секреты, только контроль частоты.
    """
    def __init__(self) -> None:
        self._last_sent: Dict[str, float] = {}
        self._last_value: Dict[str, Any] = {}

    def should_send(self, key: str, *, cooldown_sec: int, value: Any = None) -> bool:
        now = time.time()
        last = self._last_sent.get(key, 0.0)
        if now - last >= max(1, cooldown_sec):
            # если value отличается — игнорируем кулдаун (чтобы не спамить одинаковым)
            if self._last_value.get(key) != value:
                self._last_value[key] = value
                self._last_sent[key] = now
                return True
            # value тот же — проверяем по кулдауну
            self._last_sent[key] = now
            return True
        return False


def send_telegram_alert(http, token: str, chat_id: str, text: str) -> bool:
    """
    Отправляет сообщение в Telegram. Возвращает True/False по факту попытки.
    """
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        r = http.post(url, json=payload, timeout=5)
        return bool(r.status_code >= 200 and r.status_code < 300)
    except Exception:
        return False
