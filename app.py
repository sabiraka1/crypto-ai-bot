import os
import requests
import logging
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_telegram_command

# === Настройка логов ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Flask App ===
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

# === Планировщик для торговли (каждые 15 минут) ===
scheduler = BackgroundScheduler()
scheduler.add_job(check_and_trade, 'interval', minutes=15)
scheduler.start()

# === Установка Webhook ===
def set_webhook():
    bot_token = os.getenv("BOT_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")
    
    if bot_token and webhook_url:
        url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        response = requests.post(url, data={"url": webhook_url})
        logger.info(f"📡 Установка webhook: {response.status_code} - {response.text}")
    else:
        logger.error("❌ BOT_TOKEN или WEBHOOK_URL не найдены. Webhook не установлен.")

set_webhook()

# === Запуск приложения ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info("🚀 Запуск бота...")
    app.run(host='0.0.0.0', port=port)
