from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade, clean_logs
from telegram_bot import handle_command
import os
import logging
import telebot
import dotenv

dotenv.load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://yourdomain.com/webhook

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

scheduler = BackgroundScheduler()
scheduler.add_job(check_and_trade, 'interval', minutes=15)
scheduler.add_job(clean_logs, 'cron', hour=0)
scheduler.start()
logging.info("✅ Планировщик запущен (трейдинг + очистка)")

bot = telebot.TeleBot(BOT_TOKEN)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    logging.info(f"📨 Получен POST запрос на /webhook")
    logging.info(f"📨 Данные webhook: {data}")

    if "message" in data:
        try:
            handle_command(data["message"])  # 👈 ключевой вызов!
        except Exception as e:
            logging.error(f"❌ Ошибка при обработке webhook: {e}")
    return "ok", 200

@app.route("/")
def home():
    return "🤖 Бот работает!", 200

if __name__ == "__main__":
    logging.info("📡 Установка webhook...")
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    logging.info("🚀 Запуск бота...")
    app.run(host="0.0.0.0", port=10000)
