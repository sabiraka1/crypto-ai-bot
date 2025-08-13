# src/crypto_ai_bot/telegram/bot.py
"""
Telegram Bot Router для интеграции с FastAPI
"""
from fastapi import APIRouter, Request
import logging

from .commands import process_command
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.config.settings import Settings

logger = logging.getLogger(__name__)

# Создаем FastAPI router - это то, что ищет server.py
router = APIRouter()

# Инициализация зависимостей
cfg = Settings.load()
state_manager = StateManager(cfg)
exchange_client = ExchangeClient(cfg)

@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Обработка webhook от Telegram
    """
    try:
        data = await request.json()
        
        # Обработка сообщений
        if "message" in data:
            message = data["message"]
            text = message.get("text", "")
            chat_id = message.get("chat", {}).get("id")
            
            if text and chat_id:
                # Используем существующую функцию process_command из commands.py
                process_command(
                    text=text,
                    state_manager=state_manager,
                    exchange_client=exchange_client,
                    train_func=None,
                    chat_id=str(chat_id)
                )
        
        return {"ok": True}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

@router.get("/status")
async def telegram_module_status():
    """
    Статус телеграм модуля
    """
    return {
        "module": "telegram",
        "status": "active",
        "webhook_enabled": cfg.ENABLE_WEBHOOK
    }