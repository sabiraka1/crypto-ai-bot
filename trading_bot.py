import ccxt
import os
from dotenv import load_dotenv
from telegram_bot import send_telegram_message
from sinyal_skorlayici import evaluate_signal
from data_logger import log_trade
from technical_analysis import generate_signal

# Загружаем переменные из .env
load_dotenv()

api_key = os.getenv("GATE_API_KEY")
api_secret = os.getenv("GATE_API_SECRET")
chat_id = os.getenv("CHAT_ID")

# Подключение к Gate.io
exchange = ccxt.gateio({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
})

# Пара и сумма сделки
symbol = 'BTC/USDT'
amount_usdt = 10  # сумма сделки в долларах

def get_price():
    ticker = exchange.fetch_ticker(symbol)
    return ticker['last']

def execute_order(side, usdt_amount):
    price = get_price()
    amount = round(usdt_amount / price, 6)
    try:
        order = exchange.create_market_order(symbol, side, amount)
        return order
    except Exception as e:
        if chat_id:
            send_telegram_message(chat_id, f"❌ Ошибка при ордере: {e}")
        return None

def check_and_trade():
    signal = generate_signal()
    score = evaluate_signal(signal)
    price = get_price()

    if chat_id:
        message = f"📊 Сигнал: {signal}\n🤖 Оценка AI: {score:.2f}\n💰 Цена: {price}"
        send_telegram_message(chat_id, message)

    if score >= 0.8:
        side = 'buy' if signal == 'BUY' else 'sell'
        order = execute_order(side, amount_usdt)
        if order:
            log_trade(signal, score, price, success=True)
            if chat_id:
                send_telegram_message(chat_id, f"✅ Открыта сделка {side.upper()} на {amount_usdt}$")
        else:
            log_trade(signal, score, price, success=False)
    else:
        log_trade(signal, score, price, success=False)
