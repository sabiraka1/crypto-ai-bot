import os
import ccxt
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_trade
from telegram_bot import send_telegram_message

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 10))

exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

def open_position(signal, amount_usdt):
    symbol = "BTC/USDT"
    price = exchange.fetch_ticker(symbol)['last']
    amount = round(amount_usdt / price, 6)

    order_type = 'market'
    side = 'buy' if signal == "BUY" else 'sell'

    try:
        order = exchange.create_order(symbol, order_type, side, amount)
        return order, price
    except Exception as e:
        print(f"Ошибка при создании ордера: {e}")
        return None, price

def check_and_trade():
    result = generate_signal()
    signal = result["signal"]
    score = evaluate_signal(result)
    price = result["price"]

    log_trade(signal, score, price, success=(score >= 0.8))

    if signal in ["BUY", "SELL"] and score >= 0.8:
        order, exec_price = open_position(signal, TRADE_AMOUNT)
        if order:
            message = (
                f"🚀 Открыта сделка!\n"
                f"Сигнал: {signal}\n"
                f"AI Оценка: {score:.2f}\n"
                f"Цена исполнения: {exec_price:.2f}\n"
                f"Объём: {TRADE_AMOUNT} USDT"
            )
            send_telegram_message(CHAT_ID, message)
        else:
            send_telegram_message(CHAT_ID, "❌ Ошибка при попытке открыть ордер.")
    else:
        send_telegram_message(
            CHAT_ID,
            f"📊 Получен сигнал: {signal}, но оценка слишком низкая ({score:.2f}). Сделка не открыта."
        )
