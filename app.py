import os
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_telegram_command

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return "✅ Bot is alive!"

@app.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    if data:
        handle_telegram_command(data)
    return '', 200

scheduler = BackgroundScheduler()
scheduler.add_job(check_and_trade, 'interval', minutes=15)
scheduler.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("🚀 Запуск бота...")
    app.run(host='0.0.0.0', port=port)
