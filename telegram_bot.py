import os
import telebot
from signal_analyzer import analyze_bad_signals
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    bot.send_message(message.chat.id, "🤖 Привет! Я бот для трейдинга. Доступные команды:\n"
                                      "/errors — показать последние ошибки сигналов\n"
                                      "/profit — текущая прибыль\n"
                                      "/train — переобучить AI\n"
                                      "/status — статус позиции")

@bot.message_handler(commands=["errors"])
def handle_errors(message):
    summary, explanations = analyze_bad_signals(limit=5)
    
    if summary is None:
        bot.send_message(message.chat.id, "⚠️ Недостаточно данных для анализа.")
        return

    # === Статистика
    stats = "\n".join([f"{k}: {v}" for k, v in summary.items()])
    bot.send_message(message.chat.id, f"📉 Ошибки сигналов:\n\n{stats}")

    # === Причины провала
    if explanations:
        text = "\n\n".join(explanations)
        bot.send_message(message.chat.id, f"🧠 Причины последних ошибок:\n\n{text}")
    else:
        bot.send_message(message.chat.id, "✅ Нет доступных объяснений.")

@bot.message_handler(commands=["profit"])
def handle_profit(message):
    try:
        with open("closed_trades.csv", "r") as f:
            lines = f.readlines()[1:]  # skip header
        total_pnl = 0
        for line in lines:
            pnl = float(line.strip().split(",")[2])  # pnl_percent
            total_pnl += pnl
        bot.send_message(message.chat.id, f"💰 Общая доходность: {total_pnl:.2f}% по {len(lines)} сделкам.")
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Не удалось загрузить статистику: {e}")

@bot.message_handler(commands=["train"])
def handle_train(message):
    from train_model import train_model
    bot.send_message(message.chat.id, "🔄 Переобучаю AI модель...")
    try:
        train_model()
        bot.send_message(message.chat.id, "✅ Модель успешно переобучена!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при обучении: {e}")

@bot.message_handler(commands=["status"])
def handle_status(message):
    import json
    import os
    from datetime import datetime

    file = "open_position.json"
    if not os.path.exists(file):
        bot.send_message(message.chat.id, "ℹ️ Сейчас нет открытых сделок.")
        return

    with open(file, "r") as f:
        pos = json.load(f)

    ts = datetime.fromisoformat(pos['timestamp'])
    msg = (
        f"📌 Открыта позиция:\n"
        f"Тип: {pos['type'].upper()}\n"
        f"Цена входа: {pos['entry_price']}\n"
        f"Время: {ts.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Объём: {pos['amount']}\n"
        f"Оценка AI: {pos.get('score', 'N/A')}"
    )
    bot.send_message(message.chat.id, msg)

def send_telegram_message(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except Exception as e:
        print(f"❌ Ошибка при отправке в Telegram: {e}")

def run_bot():
    print("🤖 Telegram-бот запущен!")
    bot.polling(none_stop=True)
