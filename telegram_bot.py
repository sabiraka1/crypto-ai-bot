import telebot
from profit_chart import generate_profit_chart
from signal_analyzer import analyze_bad_signals
from position_tracker import get_position_status
from train_model import train_model
from grafik_olusturucu import draw_chart
from technical_analysis import generate_signal
from sinyal_skorlayici import evaluate_signal
from data_logger import log_test_trade
from config import BOT_TOKEN, CHAT_ID

bot = telebot.TeleBot(BOT_TOKEN)

# === 🟢 /start и /help
@bot.message_handler(commands=["start", "help"])
def handle_start_help(message):
    bot.send_message(
        CHAT_ID,
        "🤖 Бот активен и работает 24/7!\n\n"
        "📌 Доступные команды:\n"
        "/test — ручной тест сигнала\n"
        "/train — переобучение модели\n"
        "/status — текущая позиция\n"
        "/profit — график прибыли\n"
        "/errors — ошибки сигналов"
    )

# === 🧪 /test — ручная проверка сигнала
@bot.message_handler(commands=["test"])
def handle_test(message):
    result = generate_signal()
    score = evaluate_signal(result)
    draw_chart(result)
    log_test_trade(result["signal"], score, result["price"], result["rsi"], result["macd"])

    bot.send_message(CHAT_ID, f"🧪 Сигнал: {result['signal']}\n"
                              f"📈 RSI: {result['rsi']:.2f}, MACD: {result['macd']:.2f}\n"
                              f"🤖 AI Оценка: {score:.2f}")
    with open("charts/latest.png", "rb") as photo:
        bot.send_photo(CHAT_ID, photo)

# === 🔁 /train — ручное переобучение модели
@bot.message_handler(commands=["train"])
def handle_train(message):
    train_model()
    bot.send_message(CHAT_ID, "✅ AI-модель успешно переобучена и сохранена!")

# === 📈 /profit — график прибыли
@bot.message_handler(commands=["profit"])
def handle_profit(message):
    path = generate_profit_chart()
    if path:
        with open(path, "rb") as photo:
            bot.send_photo(CHAT_ID, photo)
    else:
        bot.send_message(CHAT_ID, "⚠️ Недостаточно данных для построения графика.")

# === ℹ️ /status — статус открытой позиции
@bot.message_handler(commands=["status"])
def handle_status(message):
    msg = get_position_status()
    bot.send_message(CHAT_ID, msg)

# === 📉 /errors — анализ ошибок
@bot.message_handler(commands=["errors"])
def handle_errors(message):
    summary, explanations = analyze_bad_signals(limit=5)
    
    if summary is None:
        bot.send_message(CHAT_ID, "⚠️ Недостаточно данных для анализа.")
        return

    stats = "\n".join([f"{k}: {v}" for k, v in summary.items()])
    bot.send_message(CHAT_ID, f"📉 Ошибки сигналов:\n\n{stats}")

    if explanations:
        text = "\n\n".join(explanations)
        bot.send_message(CHAT_ID, f"🧠 Причины последних ошибок:\n\n{text}")
    else:
        bot.send_message(CHAT_ID, "✅ Нет доступных объяснений.")

# === Запуск
def start_telegram_bot():
    print("🚀 Telegram бот запущен...")
    bot.polling(none_stop=True)
