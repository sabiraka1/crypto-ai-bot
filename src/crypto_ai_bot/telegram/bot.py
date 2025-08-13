# src/crypto_ai_bot/telegram/bot.py
"""
Telegram webhook router
- FastAPI APIRouter с эндпоинтами для вебхука
- Проверка секретного токена в query (?token=...)
- Делегирование логики в telegram.commands / telegram.api_utils
- Никаких тяжёлых импортов на уровне модуля
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException

# Настройки и утилиты (лёгкие)
try:
    from crypto_ai_bot.config.settings import Settings
except Exception:
    Settings = None  # будем читать из os.environ

from crypto_ai_bot.telegram.api_utils import send_message  # лёгкая обёртка над Telegram API

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Конфиг
# -----------------------------------------------------------------------------
def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(key, default)
    return val

def _cfg() -> Dict[str, Any]:
    # Если есть Settings — используем, иначе читаем из env
    data: Dict[str, Any] = {}
    if Settings is not None:
        try:
            s = Settings()
            data = {
                "BOT_TOKEN": s.BOT_TOKEN,
                "TELEGRAM_SECRET_TOKEN": s.TELEGRAM_SECRET_TOKEN,
                "CHAT_ID": s.CHAT_ID,
                "ENABLE_WEBHOOK": int(os.getenv("ENABLE_WEBHOOK", "1")),
            }
        except Exception as e:
            logger.warning("Settings fallback to ENV: %s", e)

    # Fallback/override из ENV
    data.setdefault("BOT_TOKEN", _get_env("BOT_TOKEN", ""))
    data.setdefault("TELEGRAM_SECRET_TOKEN", _get_env("TELEGRAM_SECRET_TOKEN", ""))
    data.setdefault("CHAT_ID", _get_env("CHAT_ID", ""))
    data.setdefault("ENABLE_WEBHOOK", int(_get_env("ENABLE_WEBHOOK", "1") or "1"))
    return data

CFG = _cfg()

# -----------------------------------------------------------------------------
# Роутер
# -----------------------------------------------------------------------------
router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/ping")
async def ping() -> Dict[str, Any]:
    """Быстрый пинг-эндпоинт для проверки, что роутер подключен."""
    return {"ok": True, "service": "telegram", "webhook_enabled": bool(CFG.get("ENABLE_WEBHOOK", 1))}


@router.get("/test")
async def test_message() -> Dict[str, Any]:
    """
    Отправить тестовое сообщение в CHAT_ID, чтобы проверить токен/доступ.
    НЕ требует секретного токена (удобно из браузера).
    """
    bot_token = CFG.get("BOT_TOKEN", "")
    chat_id = CFG.get("CHAT_ID", "")
    if not bot_token or not chat_id:
        raise HTTPException(status_code=400, detail="BOT_TOKEN or CHAT_ID not configured")
    try:
        send_message(chat_id, "✅ Telegram router is alive.")
        return {"ok": True}
    except Exception as e:
        logger.error("Telegram test failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def telegram_webhook(request: Request, token: Optional[str] = None) -> Dict[str, Any]:
    """
    Главный webhook-эндпоинт. Telegram будет слать сюда апдейты.
    Мы ПРОВЕРЯЕМ секретный токен из query (?token=...) и только потом обрабатываем.
    """
    if not CFG.get("ENABLE_WEBHOOK", 1):
        raise HTTPException(status_code=403, detail="Webhook disabled by config")

    # Проверка секретного токена
    expected = CFG.get("TELEGRAM_SECRET_TOKEN", "")
    if not expected:
        logger.warning("TELEGRAM_SECRET_TOKEN is empty — webhook is not protected!")
    if expected and token != expected:
        logger.warning("Webhook token mismatch")
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    try:
        update: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Мини-парсер апдейта
    message = update.get("message") or update.get("edited_message")
    callback = update.get("callback_query")

    # вытаскиваем чат
    chat_id: Optional[str] = None
    text: Optional[str] = None

    if message:
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id")) if chat.get("id") is not None else None
        text = message.get("text")
    elif callback:
        msg = callback.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id")) if chat.get("id") is not None else None
        text = callback.get("data")

    if not chat_id:
        # Неизвестный формат апдейта — логируем и подтверждаем, чтобы Telegram не ретраил
        logger.debug("Update without chat_id: %s", update)
        return {"ok": True}

    # Делегируем бизнес-логику в commands
    try:
        # импортим только тут, чтобы избежать лишних зависимостей/циклов
        from crypto_ai_bot.telegram.commands import process_command
    except Exception as e:
        logger.error("Failed to import commands.process_command: %s", e, exc_info=True)
        # хотя бы эхо, чтобы не молчать
        if text:
            try:
                send_message(chat_id, f"🤖 Received: {text}")
            except Exception:
                pass
        return {"ok": True}

    try:
        await process_command(chat_id=chat_id, text=text or "", update=update)
    except Exception as e:
        logger.error("Command processing failed: %s", e, exc_info=True)
        # Не падаем — отвечаем 200, чтобы Telegram не долбил ретраями
        try:
            send_message(chat_id, "⚠️ Internal error while processing your command.")
        except Exception:
            pass

    return {"ok": True}


# Опционально: утилита для чтения текущего webhook (можно вызывать руками)
@router.get("/webhook/info")
async def webhook_info() -> Dict[str, Any]:
    """
    Возвращает минимальную информацию о конфиге вебхука (с точки зрения нашего приложения).
    Это НЕ обращается к Telegram getWebhookInfo, просто помогает тебе видеть конфиг в рантайме.
    """
    return {
        "ok": True,
        "configured": bool(CFG.get("ENABLE_WEBHOOK", 1)),
        "secret_set": bool(CFG.get("TELEGRAM_SECRET_TOKEN", "")),
        "chat_id_set": bool(CFG.get("CHAT_ID", "")),
    }


__all__ = ["router"]
