# telegram_bot.py

import os
import telebot

from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# Импорты функций
from technical_analysis import generate_signal
from sinyal_skorlayici import evaluate_signal
from grafik_olusturucu import draw_chart
from data_logger import log_test_trade
from profit_chart import generate_profit_chart
from signal_analyzer import analyze_bad_signals
from train_model import retrain_model
from position_status import get_open_position_status


def handle_command(message):
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if text == "/start" or text == "/help":
        bot.send_message(
            chat_id,
            "🤖 Бот активен и работает 24/7!\n\n"
            "📌 Доступные команды:\n"
            "/test — ручной тест сигнала\n"
            "/train — переобучение модели\n"
            "/status — текущая позиция\n"
            "/profit — график прибыли\n"
            "/errors — ошибки сигналов"
        )

    elif text == "/test":
        signal_data = generate_signal()
        signal, rsi, macd, pattern, price = signal_data
        score = evaluate_signal(signal_data)
        chart_path = draw_chart(signal_data, score)
        log_test_trade(signal, score, price, rsi, macd)

        bot.send_message(
            chat_id,
            f"🧪 Ручной тест сигнала:\nСигнал: {signal}\nRSI: {rsi}\nMACD: {macd}\nScore: {score}"
        )
        if chart_path:
            with open(chart_path, "rb") as img:
                bot.send_photo(chat_id, img)

    elif text == "/train":
        retrain_model()
        bot.send_message(chat_id, "🧠 Модель успешно переобучена!")

    elif text == "/status":
        status_text = get_open_position_status()
        bot.send_message(chat_id, status_text)

    elif text == "/profit":
        chart_path = generate_profit_chart()
        if chart_path:
            with open(chart_path, "rb") as img:
                bot.send_photo(chat_id, img)
        else:
            bot.send_message(chat_id, "❌ Недостаточно данных для графика прибыли.")

    elif text == "/errors":
        summary, explanations = analyze_bad_signals()
        if not summary:
            bot.send_message(chat_id, "✅ Ошибок сигналов не обнаружено.")
            return

        text_summary = "\n".join([f"{k}: {v}" for k, v in summary.items()])
        bot.send_message(chat_id, f"❌ Обнаружены ошибки сигналов:\n{text_summary}")

        if explanations:
            bot.send_message(chat_id, "\n".join(explanations[:5]))
