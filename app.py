import os
import requests
import logging
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_telegram_command

# === Настройка логирования ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Flask-приложение ===
app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return "✅ Bot is alive!"

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("📨 Получен POST запрос на /webhook")
    try:
        data = request.get_json()
        logger.info(f"📨 Данные webhook: {data}")
        if data:
            handle_telegram_command(data)
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке webhook: {e}")
    return '', 200

# === Планировщик трейдинга (каждые 15 минут) ===
scheduler = BackgroundScheduler()
scheduler.add_job(check_and_trade, 'interval', minutes=15)
scheduler.start()
logger.info("✅ Планировщик запущен (каждые 15 минут)")

# === Автоматическая установка Webhook ===
def set_webhook():
    bot_token = os.getenv("BOT_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")
    
    if not bot_token or not webhook_url:
        logger.error("❌ BOT_TOKEN или WEBHOOK_URL не заданы.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    try:
        response = requests.post(url, data={"url": webhook_url})
        logger.info(f"📡 Установка webhook: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"❌ Ошибка установки webhook: {e}")

# === Запуск при старте ===
set_webhook()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info("🚀 Запуск бота...")
    app.run(host='0.0.0.0', port=port)
