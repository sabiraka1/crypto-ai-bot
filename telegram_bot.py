# telegram_bot.py

import os
import telebot
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_test_trade
from signal_analyzer import analyze_bad_signals
from profit_chart import generate_profit_chart
from position_status import get_position_status
from train_model import train_model

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
bot = telebot.TeleBot(BOT_TOKEN)


def handle_telegram_command(data):
    try:
        message = data['message']
        text = message.get("text", "")
        chat_id = message["chat"]["id"]

        if text.startswith("/start") or text.startswith("/help"):
            bot.send_message(chat_id,
                "🤖 Бот активен и работает 24/7!\n\n"
                "📌 Доступные команды:\n"
                "/test — ручной тест сигнала\n"
                "/train — переобучение модели\n"
                "/status — текущая позиция\n"
                "/profit — график прибыли\n"
                "/errors — ошибки сигналов"
            )

        elif text.startswith("/test"):
            result = generate_signal()
            signal = result["signal"]
            rsi = result["rsi"]
            macd = result["macd"]
            price = result["price"]
            score = evaluate_signal(result)

            log_test_trade(signal, score, price, rsi, macd)

            msg = (
                f"🧪 Ручной тест сигнала:\n"
                f"Сигнал: {signal}\n"
                f"RSI: {rsi:.2f}\n"
                f"MACD: {macd:.2f}\n"
                f"Цена: {price:.2f}\n"
                f"🤖 Оценка AI: {score:.2f}"
            )
            bot.send_message(chat_id, msg)

        elif text.startswith("/train"):
            message = train_model()
            bot.send_message(chat_id, message)

        elif text.startswith("/status"):
            status = get_position_status()
            bot.send_message(chat_id, status)

        elif text.startswith("/profit"):
            image_path = generate_profit_chart()
            if image_path:
                with open(image_path, "rb") as photo:
                    bot.send_photo(chat_id, photo)
            else:
                bot.send_message(chat_id, "⚠️ Недостаточно данных для построения графика.")

        elif text.startswith("/errors"):
            summary, explanations = analyze_bad_signals()
            if summary:
                text_lines = [f"{k}: {v}" for k, v in summary.items()]
                summary_text = "📊 Ошибки сигналов:\n" + "\n".join(text_lines)
                bot.send_message(chat_id, summary_text)

                if explanations:
                    expl = "\n\n".join(explanations)
                    bot.send_message(chat_id, f"🧠 Последние ошибки:\n{expl}")
            else:
                bot.send_message(chat_id, "✅ Ошибок сигналов не найдено или недостаточно данных.")
        else:
            bot.send_message(chat_id, "❓ Неизвестная команда. Напиши /help для списка.")
    except Exception as e:
        print(f"❌ Ошибка обработки команды: {e}")
