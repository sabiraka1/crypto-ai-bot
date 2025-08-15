# src/crypto_ai_bot/telegram/bot.py
from __future__ import annotations

import logging
from typing import Any, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.http_client import http_post  # единая точка HTTP

logger = logging.getLogger("crypto_ai_bot.telegram.bot")

_CFG: Optional[Settings] = None


def init(cfg: Settings) -> None:
    """Инициализация Telegram-бота единым Settings (без os.getenv)."""
    global _CFG
    _CFG = cfg
    logger.info("telegram.bot initialized")


def _ensure_cfg() -> Settings:
    assert _CFG is not None, "telegram.bot not initialized — call init(Settings) first"
    return _CFG


def _tg_api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def tg_send_message(text: str, chat_id: Optional[str] = None) -> tuple[bool, Any]:
    cfg = _ensure_cfg()
    token = cfg.TELEGRAM_BOT_TOKEN
    to = chat_id or cfg.TELEGRAM_CHAT_ID
    if not token or not to:
        logger.warning("Telegram token/chat_id not configured")
        return False, "not-configured"

    payload = {"chat_id": to, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    ok, data = http_post(_tg_api(token, "sendMessage"), json=payload, timeout=10)
    if not ok:
        logger.warning("tg_send_message failed: %s", data)
    return ok, data


def tg_send_photo(photo_url: str, caption: str = "", chat_id: Optional[str] = None) -> tuple[bool, Any]:
    cfg = _ensure_cfg()
    token = cfg.TELEGRAM_BOT_TOKEN
    to = chat_id or cfg.TELEGRAM_CHAT_ID
    if not token or not to:
        logger.warning("Telegram token/chat_id not configured")
        return False, "not-configured"

    payload = {"chat_id": to, "photo": photo_url, "caption": caption, "parse_mode": "HTML"}
    ok, data = http_post(_tg_api(token, "sendPhoto"), json=payload, timeout=10)
    if not ok:
        logger.warning("tg_send_photo failed: %s", data)
    return ok, data


# --- Простая обработка апдейтов (webhook) ---

def process_update(update: dict) -> None:
    """
    Минимальный обработчик Telegram-апдейта.
    Поддерживает /start, /ping и текстовые эхо.
    """
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = str(message["chat"]["id"])
        text = str(message.get("text") or "").strip()

        if text.startswith("/start"):
            tg_send_message("Бот запущен. Команда: /ping — проверка связи.", chat_id=chat_id)
            return

        if text.startswith("/ping"):
            tg_send_message("pong ✅", chat_id=chat_id)
            return

        # эхо по умолчанию (можно отключить)
        if text:
            tg_send_message(f"echo: <code>{text}</code>", chat_id=chat_id)

    except Exception as e:
        logger.exception("process_update failed: %s", e)
