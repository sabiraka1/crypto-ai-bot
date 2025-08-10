import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

from exchange_client import ExchangeClient
from position_manager import PositionManager
from performance_tracker import PerformanceTracker
from csv_handler import CSVHandler
from settings import (
    TRADING_PAIR, TP1, TP2, TP3, TP4,
    SL_PERCENT, TRAILING_STOP_PERCENT,
    SILENCE_TIMEOUT
)

from telegram_bot import send_telegram_message
from technical_analysis import generate_signal, backfill_missing_candles

# ======== Загрузка окружения ========
load_dotenv()

# ======== Логирование ========
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ======== Инициализация ========
exchange = ExchangeClient()
position_manager = PositionManager(exchange)
performance_tracker = PerformanceTracker()
csv_handler = CSVHandler()

PAIR = TRADING_PAIR or os.getenv("TRADING_PAIR", "BTC/USDT")
OPEN_POSITION_FILE = "open_position.json"
LAST_SIGNAL_TIME = datetime.utcnow()

# ======== Восстановление позиции ========
def restore_position():
    if os.path.exists(OPEN_POSITION_FILE):
        with open(OPEN_POSITION_FILE, "r") as f:
            pos = json.load(f)
        if pos.get("is_open"):
            logging.info(f"♻️ Восстановление позиции {pos['side']} {pos['symbol']} с цены {pos['entry_price']}")
            position_manager.resume_position(pos)
            send_telegram_message(
                f"♻️ <b>Восстановление позиции</b>\n"
                f"🔹 {pos['side']} {pos['symbol']}\n"
                f"📈 Цена входа: {pos['entry_price']}\n"
                f"🛡 SL: {pos['sl']}\n"
                f"🎯 TP1–TP4: {pos['tp1']}, {pos['tp2']}, {pos['tp3']}, {pos['tp4']}\n"
                f"📊 Трейлинг: {pos['trailing_stop']}%"
            )

# ======== Открытие сделки ========
def open_trade(signal, price, ai_score):
    tp_levels = {
        "tp1": price * (1 + TP1 / 100) if signal == "BUY" else price * (1 - TP1 / 100),
        "tp2": price * (1 + TP2 / 100) if signal == "BUY" else price * (1 - TP2 / 100),
        "tp3": price * (1 + TP3 / 100) if signal == "BUY" else price * (1 - TP3 / 100),
        "tp4": price * (1 + TP4 / 100) if signal == "BUY" else price * (1 - TP4 / 100)
    }
    sl_price = price * (1 - SL_PERCENT / 100) if signal == "BUY" else price * (1 + SL_PERCENT / 100)

    position_data = position_manager.open_position(
        symbol=PAIR,
        side=signal,
        amount_usd=10,
        entry_price=price,
        sl=sl_price,
        tp_levels=tp_levels,
        trailing_stop=TRAILING_STOP_PERCENT
    )

    csv_handler.log_trade_open(position_data)
    performance_tracker.log_trade_open(position_data)

    win_rate = performance_tracker.get_win_rate()
    total_pnl_usd, total_pnl_percent = performance_tracker.get_total_pnl()

    send_telegram_message(
        f"🚀 <b>Открыта позиция</b>\n"
        f"🔹 {signal} {PAIR}\n"
        f"📈 Цена: {price:.4f}\n"
        f"🎯 TP1: {tp_levels['tp1']:.4f} | TP2: {tp_levels['tp2']:.4f}\n"
        f"🎯 TP3: {tp_levels['tp3']:.4f} | TP4: {tp_levels['tp4']:.4f}\n"
        f"🛡 SL: {sl_price:.4f}\n"
        f"📊 AI Score: {ai_score:.2f}\n"
        f"📈 Win-rate: {win_rate:.2f}%\n"
        f"💰 Общий PnL: {total_pnl_usd:.2f}$ ({total_pnl_percent:.2f}%)"
    )

# ======== Обработка сигнала ========
def handle_signal(signal_data):
    global LAST_SIGNAL_TIME
    LAST_SIGNAL_TIME = datetime.utcnow()

    signal = signal_data["signal"]
    price = signal_data["price"]
    ai_score = signal_data["ai_score"]

    if position_manager.has_open_position():
        position_manager.check_exit_conditions(signal_data)
    else:
        if ai_score >= 0.7 and signal in ["BUY", "SELL"]:
            open_trade(signal, price, ai_score)

# ======== Проверка тишины ========
def check_silence_restart():
    global LAST_SIGNAL_TIME
    if datetime.utcnow() - LAST_SIGNAL_TIME > timedelta(minutes=SILENCE_TIMEOUT):
        logging.warning("⏳ Тишина. Перезапуск...")
        send_telegram_message("⏳ Долго нет сигналов. Перезапуск...")
        os.execv(sys.executable, ["python"] + sys.argv)

# ======== Главный цикл ========
def main():
    logging.info(f"Запуск бота на паре {PAIR}")
    send_telegram_message(f"🤖 Бот запущен. Пара: {PAIR}")

    restore_position()
    backfill_missing_candles(PAIR)  # автодогрузка свечей при старте

    while True:
        try:
            signal_data = generate_signal(PAIR)
            handle_signal(signal_data)
            check_silence_restart()
            time.sleep(15)

        except Exception as e:
            logging.error(f"Ошибка в главном цикле: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
