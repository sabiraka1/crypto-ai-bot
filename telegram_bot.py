import requests
import os
import ccxt
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal, draw_rsi_macd_chart
from data_logger import log_test_trade

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Настройка Gate.io
exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

def get_price():
    ticker = exchange.fetch_ticker('BTC/USDT')
    return ticker['last']

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

def send_telegram_photo(chat_id, image_path, caption=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as photo:
        files = {'photo': photo}
        data = {'chat_id': chat_id}
        if caption:
            data['caption'] = caption
        requests.post(url, data=data, files=files)

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
        result = generate_signal()
        signal = result["signal"]
        rsi = result["rsi"]
        macd = result["macd"]
        price = result["price"]
        score = evaluate_signal(result)

        log_test_trade(signal, score, price)

        caption = (
            f"🧪 Тест сигнала\n"
            f"📊 Сигнал: {signal}\n"
            f"📉 RSI: {rsi}, 📈 MACD: {macd}\n"
            f"🤖 Оценка AI: {score:.2f}\n"
            f"💰 Цена: {price}"
        )

        if score >= 0.7:
            action = "📈 AL" if signal == "BUY" else "📉 SAT"
            caption += f"\n✅ Рекомендация: {action}"

            image_path = draw_rsi_macd_chart({
                'signal': signal,
                'rsi': rsi,
                'macd': macd
            })

            if image_path:
                send_telegram_photo(chat_id, image_path, caption)
                return

        send_telegram_message(chat_id, caption)

    else:
        send_telegram_message(chat_id, f"📨 Вы написали: {text}")
