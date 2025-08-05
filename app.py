from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_telegram_command
import logging

# === Flask App ===
app = Flask(__name__)
scheduler = BackgroundScheduler()

# === Включаем логирование ===
logging.basicConfig(level=logging.INFO)

# === Планировщик торговли (каждые 15 минут) ===
scheduler.add_job(check_and_trade, 'interval', minutes=15)
scheduler.start()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if data:
        handle_telegram_command(data)
    return "OK", 200

@app.route("/alive", methods=["GET"])
def alive():
    return "🤖 Бот работает!", 200

if __name__ == "__main__":
    print("🚀 Запуск бота...")
    app.run(host="0.0.0.0", port=5000)
