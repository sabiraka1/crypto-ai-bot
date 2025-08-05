import os
import ccxt
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from telegram_utils import send_telegram_message  # вынеси сюда send_telegram_message
from data_logger import log_test_trade

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Gate.io
exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

def check_and_trade():
    result = generate_signal()
    signal = result["signal"]
    price = result["price"]

    score = evaluate_signal(result)
    log_test_trade(signal, score, price)

    message = (
        f"📊 Авто-трейдинг\n"
        f"Сигнал: {signal}\n"
        f"AI оценка: {score:.2f}\n"
        f"Цена: {price}"
    )

    if score >= 0.8 and signal in ["BUY", "SELL"]:
        action = "ПОКУПКА ✅" if signal == "BUY" else "ПРОДАЖА ❌"
        message += f"\n🚀 Открытие сделки: {action}"
        # Здесь можешь вызвать функцию для покупки через ccxt, если хочешь

    send_telegram_message(CHAT_ID, message)
