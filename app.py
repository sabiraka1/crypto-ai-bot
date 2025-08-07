import os
import logging
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_command
from dotenv import load_dotenv
import requests

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get('PORT', 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Планировщик: торговля каждые 15 минут + очистка логов каждые 6 часов
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_and_trade, trigger="interval", minutes=15, id="check_and_trade")
scheduler.start()
logger.info("✅ Планировщик запущен")

# Установка webhook Telegram
render_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
webhook_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
requests.post(webhook_url, json={"url": render_url})
logger.info(f"📡 Установка webhook: {render_url}")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if data and "message" in data:
        handle_command(data["message"])
    return "OK", 200

@app.route("/alive", methods=["GET"])
def alive():
    return "✅ Бот работает", 200

if __name__ == "__main__":
    logger.info("🚀 Flask-приложение запущено")
    app.run(host="0.0.0.0", port=PORT)
