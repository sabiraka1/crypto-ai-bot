import os
import requests
import logging

# === Настройка логирования ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Отправка сообщения в Telegram ===
def send_telegram_message(chat_id, text):
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN не найден в переменных окружения.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": text}

    try:
        response = requests.post(url, data=data)
        logger.info(f"📤 Ответ Telegram: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке сообщения в Telegram: {e}")

# === Обработка команд Telegram ===
def handle_telegram_command(data):
    logger.info(f"➡️ Обработка команды Telegram: {data}")

    try:
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        if not chat_id:
            logger.warning("⚠️ chat_id не найден в сообщении.")
            return

        if text == "/start":
            send_telegram_message(chat_id, "👋 Привет! Бот успешно запущен и работает.")
        elif text == "/test":
            send_telegram_message(chat_id, "✅ Тест пройден! Бот жив и отвечает.")
        else:
            send_telegram_message(chat_id, f"🤖 Неизвестная команда: {text}")

    except Exception as e:
        logger.error(f"❌ Ошибка в обработке команды Telegram: {e}")
