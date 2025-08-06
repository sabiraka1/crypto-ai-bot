# app.py

import os
import logging
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_telegram_command
from utils import clean_logs

app = Flask(__name__)
scheduler = BackgroundScheduler()
logging.basicConfig(level=logging.INFO)

# === 🔁 Планировщик (каждые 15 минут) ===
scheduler.add_job(check_and_trade, 'interval', minutes=15, id='check_trade')
scheduler.add_job(clean_logs, 'cron', hour=0, minute=0, id='daily_cleanup')
scheduler.start()
logging.info("✅ Планировщик запущен (трейдинг + очистка)")

# === 📡 Webhook обработка ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        logging.info(f"📨 Получен POST запрос на /webhook")
        logging.info(f"📨 Данные webhook: {data}")
        handle_telegram_command(data)
        return "OK", 200
    except Exception as e:
        logging.error(f"❌ Ошибка при обработке webhook: {e}")
        return "Error", 500

if __name__ == "__main__":
    logging.info("🚀 Запуск бота...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
