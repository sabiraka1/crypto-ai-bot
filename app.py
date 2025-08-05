from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
import logging

app = Flask(__name__)

# Настройка логгирования
logging.basicConfig(level=logging.INFO)

# Планировщик задач
scheduler = BackgroundScheduler()
scheduler.add_job(check_and_trade, 'interval', minutes=15)
scheduler.start()

@app.route('/')
def index():
    return 'Crypto AI Bot is running!'

@app.route('/alive')
def alive():
    return 'OK'

if __name__ == '__main__':
    from flask import request
from telegram_bot import handle_telegram_command

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    handle_telegram_command(data)
    return 'OK'
    app.run(debug=False, host='0.0.0.0', port=5000)
