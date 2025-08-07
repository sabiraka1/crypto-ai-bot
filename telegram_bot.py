# telegram_bot.py

import os
import telebot
from signal_analyzer import analyze_bad_signals
from position_status import get_open_position_status
from profit_chart import generate_profit_chart
from train_model import retrain_model
from sinyal_skorlayici import generate_ai_signal, plot_last_signal

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

bot = telebot.TeleBot(BOT_TOKEN)

def process_telegram_command(command):
    if command == "/start" or command == "/help":
        return (
            "🤖 Бот работает 24/7\n\n"
            "📌 Доступные команды:\n"
            "/test — ручной тест сигнала\n"
            "/train — переобучение модели\n"
            "/status — текущая позиция\n"
            "/profit — график прибыли\n"
            "/errors — ошибки сигналов"
        )

    elif command == "/status":
        return get_open_position_status()

    elif command == "/train":
        result = retrain_model()
        return f"📊 Модель переобучена!\n{result}"

    elif command == "/test":
        signal, score, rsi, macd, pattern = generate_ai_signal()
        path = plot_last_signal(signal, score)
        bot.send_photo(CHAT_ID, photo=open(path, "rb"))
        return f"🧪 Сигнал: {signal}\n📊 Score: {score:.2f}\nRSI: {rsi:.1f}, MACD: {macd:.2f}, Pattern: {pattern}"

    elif command == "/profit":
        path = generate_profit_chart()
        bot.send_photo(CHAT_ID, photo=open(path, "rb"))
        return "📈 Прибыль на графике выше."

    elif command == "/errors":
        summary, explanations = analyze_bad_signals()
        if not summary:
            return "✅ Ошибок не найдено или мало данных."
        msg = "\n".join([f"{k}: {v}" for k, v in summary.items()])
        msg += "\n\n🧠 Примеры ошибок:\n" + "\n".join(explanations)
        return msg

    else:
        return "⚠️ Неизвестная команда. Напиши /help"
