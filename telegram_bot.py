import os
from dotenv import load_dotenv
from telebot import TeleBot

from technical_analysis import generate_signal
from sinyal_skorlayici import evaluate_signal
from grafik_olusturucu import draw_rsi_macd_chart
from data_logger import log_test_trade
from profit_chart import generate_profit_chart
from signal_analyzer import analyze_bad_signals
from train_model import retrain_model
from position_status import get_open_position_status

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = TeleBot(BOT_TOKEN)

def handle_command(message):
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if text in ["/start", "/help"]:
        bot.send_message(chat_id, (
            "🤖 Бот работает!\n\n"
            "📌 Команды:\n"
            "/test — тест сигнала\n"
            "/train — переобучение AI\n"
            "/status — открытая позиция\n"
            "/profit — график прибыли\n"
            "/errors — ошибки сигналов"
        ))

    elif text == "/test":
        signal_data = generate_signal()
        score = evaluate_signal(signal_data)
        chart_path = draw_rsi_macd_chart(signal_data)
        log_test_trade(
            signal_data["signal"],
            score,
            signal_data["price"],
            signal_data["rsi"],
            signal_data["macd"]
        )
        bot.send_message(chat_id,
            f"🧪 Тест сигнала\n"
            f"Сигнал: {signal_data['signal']}\n"
            f"RSI: {signal_data['rsi']} / MACD: {signal_data['macd']}\n"
            f"📈 AI: {score:.2f}"
        )
        if chart_path:
            with open(chart_path, "rb") as img:
                bot.send_photo(chat_id, img)

    elif text == "/train":
        retrain_model()
        bot.send_message(chat_id, "🧠 Модель переобучена!")

    elif text == "/status":
        status = get_open_position_status()
        bot.send_message(chat_id, status)

    elif text == "/profit":
        chart_path, profit = generate_profit_chart()
        if chart_path:
            with open(chart_path, "rb") as img:
                bot.send_photo(chat_id, img)
        else:
            bot.send_message(chat_id, "❌ Недостаточно данных для прибыли.")

    elif text == "/errors":
        summary, explanations = analyze_bad_signals()
        if not summary:
            bot.send_message(chat_id, "✅ Ошибок не найдено.")
            return
        bot.send_message(chat_id, "\n".join([f"{k}: {v}" for k, v in summary.items()]))
        if explanations:
            bot.send_message(chat_id, "\n".join(explanations[:5]))
