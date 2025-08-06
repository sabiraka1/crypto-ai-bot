import os
import telebot
import pandas as pd
import json
from signal_analyzer import analyze_bad_signals
from train_model import train_model

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=["start"])
def handle_start(message):
    bot.send_message(message.chat.id, "👋 Привет! Я трейдинг-бот. Готов к работе.")

@bot.message_handler(commands=["profit"])
def handle_profit(message):
    try:
        df = pd.read_csv("closed_trades.csv")
        if df.empty:
            bot.send_message(message.chat.id, "📭 Пока нет завершённых сделок.")
            return

        total = df["pnl_percent"].sum()
        count = len(df)
        win_count = len(df[df["pnl_percent"] > 0])
        win_rate = round((win_count / count) * 100, 2)

        response = (
            f"📈 Прибыль по {count} сделкам:\n\n"
            f"💰 Общая доходность: {total:.2f}%\n"
            f"✅ Побед: {win_count} ({win_rate}%)"
        )
        bot.send_message(message.chat.id, response)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при расчёте прибыли: {e}")

@bot.message_handler(commands=["train"])
def handle_train(message):
    try:
        train_model()
        bot.send_message(message.chat.id, "✅ AI-модель успешно переобучена!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при переобучении: {e}")

@bot.message_handler(commands=["status"])
def handle_status(message):
    try:
        with open("open_position.json", "r") as f:
            pos = json.load(f)

        entry = pos["entry_price"]
        time = pos["timestamp"]
        typ = pos["type"]
        score = pos.get("score", "—")

        response = (
            f"📌 Открытая позиция:\n\n"
            f"Тип: {typ.upper()}\n"
            f"Цена входа: {entry:.2f}\n"
            f"Открыта: {time}\n"
            f"AI Score: {score}"
        )
        bot.send_message(message.chat.id, response)
    except:
        bot.send_message(message.chat.id, "ℹ️ Позиция не открыта.")

@bot.message_handler(commands=["errors"])
def handle_errors(message):
    summary, explanations = analyze_bad_signals(limit=5)
    
    if summary is None:
        bot.send_message(message.chat.id, "⚠️ Недостаточно данных для анализа.")
        return

    stats = "\n".join([f"{k}: {v}" for k, v in summary.items()])
    bot.send_message(message.chat.id, f"📉 Ошибки сигналов:\n\n{stats}")

    if explanations:
        text = "\n\n".join(explanations)
        bot.send_message(message.chat.id, f"🧠 Причины последних ошибок:\n\n{text}")
    else:
        bot.send_message(message.chat.id, "✅ Нет доступных объяснений.")

# Запуск бота
print("🤖 Telegram-бот запущен.")
bot.polling(none_stop=True)
