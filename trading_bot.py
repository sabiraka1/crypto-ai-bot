import os, json, logging
import ccxt
from datetime import datetime
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_trade, log_closed_trade
from telegram_bot import bot
from train_model import train_model

load_dotenv()

CHAT_ID = os.getenv("CHAT_ID")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 10))
PROFIT_TARGET = 0.02
MAX_HOLD_MINUTES = 120
POSITION_FILE = "open_position.json"
RSI_MEMORY_FILE = "rsi_memory.json"

exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

def send_telegram_message(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def get_open_position():
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, 'r') as f:
            return json.load(f)
    return None

def save_position(data):
    with open(POSITION_FILE, 'w') as f:
        json.dump(data, f)

def clear_position():
    if os.path.exists(POSITION_FILE):
        os.remove(POSITION_FILE)

def update_rsi_memory(rsi):
    memory = []
    if os.path.exists(RSI_MEMORY_FILE):
        with open(RSI_MEMORY_FILE, 'r') as f:
            memory = json.load(f)
    memory.append(rsi)
    memory = memory[-6:]
    with open(RSI_MEMORY_FILE, 'w') as f:
        json.dump(memory, f)

def is_rsi_high():
    if os.path.exists(RSI_MEMORY_FILE):
        with open(RSI_MEMORY_FILE, 'r') as f:
            memory = json.load(f)
        return len(memory) == 6 and all(r > 70 for r in memory)
    return False

def close_position(position, reason, signal=None, score=None):
    symbol = position['symbol']
    side = 'sell' if position['type'] == 'buy' else 'buy'
    price_now = exchange.fetch_ticker(symbol)['last']
    amount = position['amount']
    entry_price = position['entry_price']

    try:
        exchange.create_order(symbol, 'market', side, amount)
        profit = (price_now - entry_price) / entry_price
        if position['type'] == 'sell':
            profit = -profit

        log_closed_trade(entry_price, price_now, profit, reason,
                         signal or position['type'].upper(), score or 0.0,
                         position.get("rsi"), position.get("macd"))

        send_telegram_message(CHAT_ID,
            f"❎ Сделка закрыта\nЦена: {entry_price} → {price_now}\nДоход: {profit*100:.2f}%\nПричина: {reason}"
        )
        train_model()
        clear_position()
    except Exception as e:
        send_telegram_message(CHAT_ID, f"❌ Ошибка закрытия сделки: {e}")

def check_close_conditions(rsi):
    position = get_open_position()
    if not position:
        return
    now = datetime.utcnow()
    opened_at = datetime.fromisoformat(position['timestamp'])
    held = (now - opened_at).total_seconds() / 60
    price_now = exchange.fetch_ticker(position['symbol'])['last']
    profit = (price_now - position['entry_price']) / position['entry_price']
    if position['type'] == 'sell':
        profit = -profit
    update_rsi_memory(rsi)

    if profit >= PROFIT_TARGET:
        close_position(position, "profit")
    elif rsi > 85:
        close_position(position, "rsi>85")
    elif is_rsi_high():
        close_position(position, "rsi>70_90min")
    elif held > MAX_HOLD_MINUTES:
        close_position(position, "timeout")

def open_position(signal, usdt, rsi=None, macd=None, score=None):
    symbol = "BTC/USDT"
    price = exchange.fetch_ticker(symbol)['last']
    amount = round(usdt / price, 6)
    side = 'buy' if signal == "BUY" else 'sell'

    try:
        exchange.create_order(symbol, 'market', side, amount)
        save_position({
            "symbol": symbol,
            "type": side,
            "entry_price": price,
            "amount": amount,
            "timestamp": datetime.utcnow().isoformat(),
            "rsi": rsi,
            "macd": macd,
            "score": score or 0.0
        })
        if os.path.exists(RSI_MEMORY_FILE):
            os.remove(RSI_MEMORY_FILE)
        return True, price
    except Exception as e:
        send_telegram_message(CHAT_ID, f"❌ Ошибка открытия ордера: {e}")
        return False, price

def check_and_trade():
    send_telegram_message(CHAT_ID, \"\\U0001f501 check_and_trade() запущен\")
    result = generate_signal()
    signal = result[\"signal\"]
    score = evaluate_signal(result)
    log_trade(signal, score, result[\"price\"], result[\"rsi\"], result[\"macd\"], success=(score >= 0.6))
    check_close_conditions(result[\"rsi\"])

    if signal in [\"BUY\", \"SELL\"] and score >= 0.6:
        if get_open_position():
            send_telegram_message(CHAT_ID, \"⚠️ Сделка уже открыта. Жду закрытия.\")
        else:
            ok, price = open_position(signal, TRADE_AMOUNT, result[\"rsi\"], result[\"macd\"], score)
            if ok:
                send_telegram_message(CHAT_ID, f\"🚀 Сделка открыта: {signal} @ {price:.2f}\")
