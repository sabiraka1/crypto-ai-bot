# telegram_bot.py (обновлённый для webhook)

import os
import logging
import telebot
from signal_analyzer import analyze_bad_signals
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from data_logger import log_test_trade
from train_model import train_model
from profit_chart import generate_profit_chart
from position_status import get_open_position_status

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
bot = telebot.TeleBot(BOT_TOKEN)
logger = logging.getLogger(__name__)

def handle_telegram_command(data):
    try:
        message = data.get("message", {})
        text = message.get("text", "").strip()
        chat_id = message.get("chat", {}).get("id")

        if text == "/start" or text == "/help":
            bot.send_message(chat_id, (
                "🤖 Бот активен и работает 24/7!\n\n"
                "📌 Доступные команды:\n"
                "/test — ручной тест сигнала\n"
                "/train — переобучение модели\n"
                "/status — текущая позиция\n"
                "/profit — график прибыли\n"
                "/errors — ошибки сигналов"
            ))

        elif text == "/test":
            result = generate_signal()
            score = evaluate_signal(result)
            log_test_trade(
                signal=result['signal'],
                score=score,
                price=result['price'],
                rsi=result['rsi'],
                macd=result['macd']
            )
            msg = (
                f"🧪 Оценка сигнала: {result['signal']}, RSI: {result['rsi']:.2f}, MACD: {result['macd']:.2f}\n"
                f"🤖 AI Score: {score:.2f}"
            )
            bot.send_message(chat_id, msg)

        elif text == "/train":
            msg = train_model()
            bot.send_message(chat_id, msg)

        elif text == "/status":
            status = get_open_position_status()
            bot.send_message(chat_id, status)

        elif text == "/profit":
            chart_path = generate_profit_chart()
            with open(chart_path, 'rb') as img:
                bot.send_photo(chat_id, img)

        elif text == "/errors":
            summary, explanations = analyze_bad_signals(limit=5)
            if not summary:
                bot.send_message(chat_id, "✅ Ошибок не обнаружено")
            else:
                text_summary = "\n".join([f"{k}: {v}" for k, v in summary.items()])
                bot.send_message(chat_id, f"📉 Анализ ошибок:\n{text_summary}")
                for explanation in explanations:
                    bot.send_message(chat_id, explanation)

        else:
            bot.send_message(chat_id, "❌ Неизвестная команда")

    except Exception as e:
        logger.error(f"Ошибка обработки Telegram-команды: {e}")
