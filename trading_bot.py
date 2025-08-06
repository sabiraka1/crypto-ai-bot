import os
import json
import ccxt
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_trade
from telegram_bot import send_telegram_message

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 10))
PROFIT_TARGET = 0.02  # 2%
MAX_HOLD_MINUTES = 120  # 2 часа

POSITION_FILE = "open_position.json"

exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

# === Чтение открытой позиции ===
def get_open_position():
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, 'r') as f:
            return json.load(f)
    return None

# === Сохранение новой позиции ===
def save_position(data):
    with open(POSITION_FILE, 'w') as f:
        json.dump(data, f)

# === Удаление позиции ===
def clear_position():
    if os.path.exists(POSITION_FILE):
        os.remove(POSITION_FILE)

# === Закрытие сделки ===
def close_position(position):
    symbol = position['symbol']
    side = 'sell' if position['type'] == 'buy' else 'buy'
    amount = position['amount']
    price_now = exchange.fetch_ticker(symbol)['last']

    try:
        order = exchange.create_order(symbol, 'market', side, amount)
        profit = (price_now - position['entry_price']) / position['entry_price']
        message = (
            f"❎ Сделка закрыта!\n"
            f"💵 Тип: {side.upper()}\n"
            f"📈 Вход: {position['entry_price']:.2f}, Выход: {price_now:.2f}\n"
            f"📊 Доходность: {profit*100:.2f}%"
        )
        send_telegram_message(CHAT_ID, message)
        clear_position()
    except Exception as e:
        print(f"❌ Ошибка при закрытии позиции: {e}")
        send_telegram_message(CHAT_ID, "❌ Ошибка при закрытии позиции!")

# === Проверка на закрытие ===
def check_close_conditions(rsi):
    position = get_open_position()
    if not position:
        return

    now = datetime.utcnow()
    opened_at = datetime.fromisoformat(position['timestamp'])
    time_held = (now - opened_at).total_seconds() / 60
    price_now = exchange.fetch_ticker(position['symbol'])['last']
    profit = (price_now - position['entry_price']) / position['entry_price']
    if position['type'] == 'sell':
        profit = -profit  # обратное направление

    # Условия закрытия:
    if profit >= PROFIT_TARGET or rsi > 85 or time_held > MAX_HOLD_MINUTES:
        close_position(position)

# === Открытие сделки ===
def open_position(signal, amount_usdt):
    symbol = "BTC/USDT"
    price = exchange.fetch_ticker(symbol)['last']
    amount = round(amount_usdt / price, 6)
    side = 'buy' if signal == "BUY" else 'sell'

    try:
        order = exchange.create_order(symbol, 'market', side, amount)
        save_position({
            "symbol": symbol,
            "type": side,
            "entry_price": price,
            "amount": amount,
            "timestamp": datetime.utcnow().isoformat()
        })
        return order, price
    except Exception as e:
        print(f"❌ Ошибка при создании ордера: {e}")
        return None, price

# === Основная логика ===
def check_and_trade():
    result = generate_signal()
    signal = result["signal"]
    rsi = result["rsi"]
    macd = result["macd"]
    price = result["price"]
    patterns = result.get("patterns", [])

    score = evaluate_signal(result)
    log_trade(signal, score, price, rsi, macd, success=(score >= 0.7))

    # === Проверка на закрытие перед новой сделкой ===
    check_close_conditions(rsi)

    # === Открытие новой сделки ===
    if signal in ["BUY", "SELL"] and score >= 0.7:
        if get_open_position():
            send_telegram_message(CHAT_ID, "⚠️ Сделка уже открыта. Ожидание закрытия.")
            return

        order, exec_price = open_position(signal, TRADE_AMOUNT)
        if order:
            message = (
                f"🚀 Открыта сделка!\n"
                f"Сигнал: {signal}\n"
                f"📌 Паттерны: {', '.join(patterns) if patterns else 'нет'}\n"
                f"🤖 Оценка AI: {score:.2f}\n"
                f"💰 Цена: {exec_price:.2f}\n"
                f"💵 Объём: {TRADE_AMOUNT} USDT"
            )
            send_telegram_message(CHAT_ID, message)
        else:
            send_telegram_message(CHAT_ID, "❌ Ошибка при открытии ордера.")
    else:
        send_telegram_message(
            CHAT_ID,
            f"📊 Сигнал: {signal} (оценка {score:.2f}) — сделка не открыта."
        )
