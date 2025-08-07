# ✅ app.py — обновлённый файл с поддержкой webhook и всех команд
import os
import logging
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_message
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get('PORT', 10000))

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация Flask
app = Flask(__name__)

# Планировщик задач
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_and_trade, trigger="interval", minutes=15, id="check_and_trade")
scheduler.add_job(func=lambda: logger.info("🧹 Очистка логов"), trigger="interval", hours=6, id="clean_logs")
scheduler.start()
logger.info("✅ Планировщик запущен (трейдинг + очистка)")

# Настройка webhook для Telegram
import requests
webhook_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
render_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
response = requests.post(webhook_url, json={"url": render_url})
logger.info(f"📡 Установка webhook: {response.status_code} - {response.text}")

# Обработка webhook от Telegram
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logger.info(f"📨 Получен POST запрос на /webhook")
    logger.info(f"📨 Данные webhook: {data}")
    try:
        if "message" in data:
            handle_message(data["message"])
        return "OK", 200
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке webhook: {e}")
        return "Error", 500

# Проверка работоспособности
@app.route("/alive", methods=["GET"])
def alive():
    return "✅ Бот работает", 200

# Запуск приложения
if __name__ == "__main__":
    logger.info("🚀 Запуск бота...")
    app.run(host="0.0.0.0", port=PORT)
