import requests
import os
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_test_trade

BOT_TOKEN = os.getenv("BOT_TOKEN")

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    response = requests.post(url, json=payload)
    return response

def handle_telegram_command(data):
    message = data.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "")

    if not chat_id or not text:
        return

    if text.lower() in ["/start", "start"]:
        send_telegram_message(chat_id, "🤖 Бот активен! Готов к работе.")
    
    elif text.lower() == "/test":
        signal = generate_signal()
        score = evaluate_signal(signal)
        price = get_price()

        log_test_trade(signal, score, price)

        message = f"🧪 Тест сигнала\n📊 Сигнал: {signal}\n🤖 Оценка AI: {score:.2f}\n💰 Цена: {price}"
        send_telegram_message(chat_id, message)

    else:
        send_telegram_message(chat_id, f"📨 Вы написали: {text}")

def get_price():
    import ccxt
    exchange = ccxt.gateio({
        'apiKey': os.getenv("GATE_API_KEY"),
        'secret': os.getenv("GATE_API_SECRET"),
        'enableRateLimit': True
    })
    ticker = exchange.fetch_ticker('BTC/USDT')
    return ticker['last']
