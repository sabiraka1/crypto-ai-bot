# src/crypto_ai_bot/telegram/api_utils.py
"""
Телеграм-утилиты: безопасная отправка сообщений/фото.
- Работает через Settings.load()
- Если токен/чат не заданы — тихо пропускает (не ломает бота)
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any

import requests

from crypto_ai_bot.config.settings import Settings

logger = logging.getLogger(__name__)


# Экспортируем список админов как константу (для команд/фильтрации)
try:
    ADMIN_CHAT_IDS = [str(x) for x in (Settings.load().ADMIN_CHAT_IDS or [])]
except Exception:
    ADMIN_CHAT_IDS = []


def _tg_base_url(cfg: Settings) -> str:
    return f"https://api.telegram.org/bot{cfg.BOT_TOKEN}"


def _resolve_chat_id(cfg: Settings, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return str(explicit)
    if cfg.CHAT_ID:
        return str(cfg.CHAT_ID)
    if cfg.ADMIN_CHAT_IDS:
        return str(cfg.ADMIN_CHAT_IDS[0])
    return None


def send_message(
    text: str,
    chat_id: Optional[str] = None,
    disable_notification: bool = True,
    parse_mode: str = "HTML",
) -> bool:
    """Отправляет текстовое сообщение в Telegram. Возвращает True/False."""
    try:
        cfg = Settings.load()
        if not cfg.BOT_TOKEN:
            logger.debug("Telegram: BOT_TOKEN пуст — пропускаю отправку.")
            return False
        cid = _resolve_chat_id(cfg, chat_id)
        if not cid:
            logger.debug("Telegram: CHAT_ID не задан — пропускаю отправку.")
            return False

        payload: Dict[str, Any] = {
            "chat_id": cid,
            "text": text,
            "disable_notification": disable_notification,
            "parse_mode": parse_mode,
        }
        url = _tg_base_url(cfg) + "/sendMessage"
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            return True
        logger.warning(f"Telegram sendMessage failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram sendMessage error: {e}")
        return False


def send_photo(
    photo_path: str,
    caption: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
) -> bool:
    """Отправляет локальный файл как фото. Возвращает True/False."""
    try:
        cfg = Settings.load()
        if not cfg.BOT_TOKEN:
            logger.debug("Telegram: BOT_TOKEN пуст — пропускаю отправку фото.")
            return False
        cid = _resolve_chat_id(cfg, chat_id)
        if not cid:
            logger.debug("Telegram: CHAT_ID не задан — пропускаю отправку фото.")
            return False

        url = _tg_base_url(cfg) + "/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data: Dict[str, Any] = {"chat_id": cid, "caption": caption or "", "parse_mode": parse_mode}
            resp = requests.post(url, data=data, files=files, timeout=20)
        if resp.ok:
            return True
        logger.warning(f"Telegram sendPhoto failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram sendPhoto error: {e}")
        return False


__all__ = ["send_message", "send_photo", "ADMIN_CHAT_IDS"]
