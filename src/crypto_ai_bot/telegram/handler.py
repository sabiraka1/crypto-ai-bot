# src/crypto_ai_bot/telegram/handler.py
"""
Единая «фасадная» точка для Telegram-отправок/обработчика.
Никакой логики — только делегирование в telegram.bot.

Оставляет совместимость для старых импортов вида:
- from crypto_ai_bot.telegram.handler import send_telegram_message
- from crypto_ai_bot.telegram.handler import process_update
"""

from __future__ import annotations

from typing import Optional, Any

# Реальная реализация живёт в telegram.bot
from crypto_ai_bot.telegram.bot import (
    init as tg_init,
    tg_send_message,
    tg_send_photo,
    process_update as tg_process_update,
)

# Публичные имена, которые используются сервером/утилитами:
init = tg_init


def send_telegram_message(text: str, chat_id: Optional[str] = None) -> tuple[bool, Any]:
    """Совместимое имя для отправки текста."""
    return tg_send_message(text, chat_id=chat_id)


def send_telegram_photo(photo_url: str, caption: str = "", chat_id: Optional[str] = None) -> tuple[bool, Any]:
    """Совместимое имя для отправки фото/PNG."""
    return tg_send_photo(photo_url, caption=caption, chat_id=chat_id)


def process_update(update: dict) -> None:
    """Проксируем обработку апдейта."""
    return tg_process_update(update)
