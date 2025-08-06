import os
import json
import logging
import ccxt
from datetime import datetime
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_trade, log_closed_trade
from telegram_bot import send_telegram_message

load_dotenv()

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 10))
PROFIT_TARGET = 0.02  # 2%
MAX_HOLD_MINUTES = 120

POSITION_FILE = "open_position.json"

exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

def get_open_position():
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, 'r') as f:
            try:
                return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка чтения open_position.json: {e}")
    return None

def save_position(data):
    with open(POSITION_FILE, 'w') as f:
        json.dump(data, f)

def clear_position():
    if os.path.exists(POSITION_FILE):
        os.remove(POSITION_FILE)

def close_position(position, reason="manual", signal=None, score=None):
    from train_model import train_model

    symbol = position['symbol']
    side = 'sell' if position['type'] == 'buy' else 'buy'
    amount = position['amount']
    entry_price = position['entry_price']
    price_now = exchange.fetch_ticker(symbol)['last']

    try:
        order = exchange.create_order(symbol, 'market', side, amount)
        profit = (price_now - entry_price) / entry_price
        if position['type'] == 'sell':
            profit = -profit

        log_closed_trade(
            entry_price=entry_price,
            close_price=price_now,
            pnl_percent=profit,
            reason=reason,
            signal=signal or position['type'].upper(),
            score=score if score is not None else position.get("score", 0.0)
        )

        message = (
            f"❎ Сделка закрыта!\n"
            f"📉 Тип: {side.upper()}\n"
            f"💵 Вход: {entry_price:.2f}, Выход: {price_now:.2f}\n"
            f"📊 Доходность: {profit*100:.2f}%\n"
            f"📌 Причина: {reason.upper()}\n"
            f"🤖 Переобучение AI модели..."
        )
        send_telegram_message(CHAT_ID, message)

        train_model()
        send_telegram_message(CHAT_ID, "✅ AI-модель успешно переобучена и сохранена!")

        clear_position()

    except Exception as e:
        logger.error(f"❌ Ошибка при закрытии позиции: {e}")
        send_telegram_message(CHAT_ID, "❌ Ошибка при закрытии позиции!")

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
        profit = -profit

    if profit >= PROFIT_TARGET:
        close_position(position, reason="profit")
    elif rsi > 85:
        close_position(position, reason="rsi")
    elif time_held > MAX_HOLD_MINUTES:
        close_position(position, reason="timeout")

def open_position(signal, amount_usdt):
    symbol = "BTC/USDT"
    price = exchange.fetch_ticker(symbol)['last']
    amount = round(amount_usdt / price, 6)
    side = 'buy' if signal == "BUY" else 'sell'

    try:
        send_telegram_message(CHAT_ID, f"📥 Попытка открыть ордер: {side.upper()} на {amount} {symbol}")
        order = exchange.create_order(symbol, 'market', side, amount)
        save_position({
            "symbol": symbol,
            "type": side,
            "entry_price": price,
            "amount": amount,
            "timestamp": datetime.utcnow().isoformat(),
            "score": 0.0
        })
        return order, price
    except Exception as e:
        logger.error(f"❌ Ошибка при создании ордера: {e}")
        send_telegram_message(CHAT_ID, f"❌ Ошибка при создании ордера: {e}")
        return None, price

def check_and_trade():
    logger.info("🔁 check_and_trade() вызвана планировщиком.")
    send_telegram_message(CHAT_ID, "🔁 check_and_trade() запущена планировщиком.")

    result = generate_signal()
    signal = result["signal"]
    rsi = result["rsi"]
    macd = result["macd"]
    price = result["price"]
    patterns = result.get("patterns", [])

    logger.info(f"📊 Сигнал: {signal}, RSI: {rsi:.2f}, MACD: {macd:.2f}, Цена: {price}")
    send_telegram_message(CHAT_ID, f"📊 Сигнал: {signal}, RSI: {rsi:.2f}, MACD: {macd:.2f}, Цена: {price}")

    score = evaluate_signal(result)
    log_trade(signal, score, price, rsi, macd, success=(score >= 0.7))

    send_telegram_message(CHAT_ID, f"🧠 Оценка AI: {score:.2f}")

    check_close_conditions(rsi)

    if signal in ["BUY", "SELL"]:
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
