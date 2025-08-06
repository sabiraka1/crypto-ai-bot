import os
import logging
import telebot
from sinyal_skorlayici import skorlama_yap
from technical_analysis import generate_signal
from data_logger import log_signal
from signal_analyzer import analyze_errors
from profit_chart import generate_profit_chart
from train_model import retrain_model
from grafik_olusturucu import create_signal_graph
from profit_analysis import get_profitability_text

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bot = telebot.TeleBot(BOT_TOKEN)

def send_telegram_message(message, image_path=None):
    try:
        bot.send_message(CHAT_ID, message)
        if image_path:
            with open(image_path, 'rb') as img:
                bot.send_photo(CHAT_ID, img)
    except Exception as e:
        logging.error(f"❌ Ошибка отправки в Telegram: {e}")

def set_webhook(bot, webhook_url):
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)

def process_telegram_command(bot, chat_id, command):
    try:
        if command == "/start":
            bot.send_message(chat_id, "🤖 Бот активен и работает 24/7! Напиши /test, /profit или /errors.")

        elif command == "/test":
            signal, rsi, macd, pattern, price = generate_signal()
            skor = skorlama_yap([[rsi, macd, 0 if not pattern else 1]])
            log_signal(signal, skor, rsi, macd, pattern, price)
            grafik_path = create_signal_graph(rsi, macd, pattern)
            text = f"📉 Тест сигнала\n📊 Сигнал: {signal}\n📈 RSI: {rsi}, 📉 MACD: {macd}\n📑 Паттерны: {pattern or 'нет'}\n🤖 Оценка AI: {skor:.2f}\n💰 Цена: {price}"
            send_telegram_message(text, grafik_path)

        elif command == "/errors":
            result_path = analyze_errors()
            send_telegram_message("❗ Ошибочные сигналы проанализированы:", result_path)

        elif command == "/profit":
            text, chart_path = get_profitability_text()
            send_telegram_message(text, chart_path)

        elif command == "/train":
            retrain_model()
            send_telegram_message("🤖 AI-модель переобучена на новых данных.")

        else:
            bot.send_message(chat_id, "❓ Неизвестная команда. Напиши /test, /profit или /errors.")

    except Exception as e:
        logging.error(f"❌ Ошибка в обработке команды Telegram: {e}")
