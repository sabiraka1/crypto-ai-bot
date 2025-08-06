import os
import ccxt
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_trade
from telegram_bot import send_telegram_message

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 10))
PROFIT_TARGET = 0.02  # 2%
MAX_HOLDING_HOURS = 2

POSITION_FILE = "open_position.json"

exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

def save_open_position(signal, amount, price):
    position = {
        "signal": signal,
        "amount": amount,
        "entry_price": price,
        "timestamp": datetime.utcnow().isoformat()
    }
    with open(POSITION_FILE, 'w') as f:
        json.dump(position, f)

def load_open_position():
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, 'r') as f:
            return json.load(f)
    return None

def clear_open_position():
    if os.path.exists(POSITION_FILE):
        os.remove(POSITION_FILE)

def close_position_if_needed():
    pos = load_open_position()
    if not pos:
        return

    current_price = exchange.fetch_ticker("BTC/USDT")['last']
    entry = pos['entry_price']
    amount = pos['amount']
    signal = pos['signal']
    timestamp = datetime.fromisoformat(pos['timestamp'])

    # RSI Check
    result = generate_signal()
    rsi = result["rsi"]

    holding_time = datetime.utcnow() - timestamp
    pnl = (current_price - entry) / entry if signal == "BUY" else (entry - current_price) / entry

    if pnl >= PROFIT_TARGET or rsi > 85 or holding_time > timedelta(hours=MAX_HOLDING_HOURS):
        side = 'sell' if signal == "BUY" else 'buy'

        try:
            order = exchange.create_order("BTC/USDT", 'market', side, amount)
            clear_open_position()
            send_telegram_message(
                CHAT_ID,
                f"💰 Сделка закрыта по {'профиту' if pnl >= PROFIT_TARGET else 'условию'}:\n"
                f"📈 PnL: {pnl*100:.2f}%\n"
                f"📉 RSI: {rsi:.2f}\n"
                f"⏱️ Время удержания: {holding_time}"
            )
        except Exception as e:
            print(f"❌ Ошибка при закрытии позиции: {e}")

def open_position(signal, amount_usdt):
    symbol = "BTC/USDT"
    price = exchange.fetch_ticker(symbol)['last']
    amount = round(amount_usdt / price, 6)

    side = 'buy' if signal == "BUY" else 'sell'

    try:
        order = exchange.create_order(symbol, 'market', side, amount)
        save_open_position(signal, amount, price)
        return order, price
    except Exception as e:
        print(f"❌ Ошибка при создании ордера: {e}")
        return None, price

def check_and_trade():
    close_position_if_needed()

    result = generate_signal()
    signal = result["signal"]
    rsi = result["rsi"]
    macd = result["macd"]
    price = result["price"]
    patterns = result.get("patterns", [])

    score = evaluate_signal(result)
    log_trade(signal, score, price, rsi, macd, success=(score >= 0.7))

    if signal in ["BUY", "SELL"] and score >= 0.7:
        order, exec_price = open_position(signal, TRADE_AMOUNT)
        if order:
            message = (
                f"🚀 Открыта сделка!\n"
                f"Сигнал: {signal}\n"
                f"📌 Паттерны: {', '.join(patterns) if patterns else 'нет'}\n"
                f"🤖 Оценка AI: {score:.2f}\n"
                f"💰 Цена исполнения: {exec_price:.2f}\n"
                f"💵 Объём: {TRADE_AMOUNT} USDT"
            )
            send_telegram_message(CHAT_ID, message)
        else:
            send_telegram_message(CHAT_ID, "❌ Ошибка при попытке открыть ордер.")
    else:
        send_telegram_message(
            CHAT_ID,
            f"📊 Сигнал: {signal} (оценка {score:.2f}) — сделка не открыта."
        )
