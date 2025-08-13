import os
import logging
from typing import Optional, Dict

import requests

from config.settings import TradingConfig

# ── Конфигурация ──────────────────────────────────────────────────────────────
CFG = TradingConfig()

BOT_TOKEN = CFG.BOT_TOKEN
CHAT_ID = CFG.CHAT_ID
ADMIN_CHAT_IDS = CFG.ADMIN_CHAT_IDS
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


def _tg_request(method: str, data: Dict, files: Optional[Dict] = None) -> None:
    """Базовый запрос к Telegram API."""
    if not TELEGRAM_API:
        logging.warning("Telegram not configured (BOT_TOKEN missing)")
        return

    url = f"{TELEGRAM_API}/{method}"
    try:
        resp = requests.post(url, data=data, files=files, timeout=15)
        if resp.status_code != 200:
            logging.error("Telegram API error: %s %s", resp.status_code, resp.text[:200])
        else:
            logging.debug("[TG] %s ok", method)
    except Exception as e:
        logging.exception("Telegram request failed: %s", e)


def send_message(text: str, chat_id: str = None) -> None:
    """Отправка сообщения в Telegram."""
    target_chat = chat_id or CHAT_ID
    if target_chat:
        _tg_request("sendMessage", {"chat_id": target_chat, "text": text})


def send_photo(image_path: str, caption: Optional[str] = None, chat_id: str = None) -> None:
    """Отправка фото в Telegram."""
    target_chat = chat_id or CHAT_ID
    if not target_chat:
        return

    if not os.path.exists(image_path):
        logging.warning("send_photo: file not found: %s", image_path)
        return

    with open(image_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": target_chat}
        if caption:
            data["caption"] = caption
        _tg_request("sendPhoto", data, files=files)