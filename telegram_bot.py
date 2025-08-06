import os
import requests
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from grafik_olusturucu import draw_rsi_macd_chart
from profit_analysis import generate_profit_chart  # 📊 График доходности
from signal_analyzer import analyze_bad_signals  # ❌ Анализ ошибок
from data_logger import log_test_trade

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# === Отправка текстового сообщения ===
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"❌ Ошибка при отправке сообщения: {e}")

# === Отправка изображения ===
def send_telegram_photo(chat_id, image_path, caption=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(image_path, 'rb') as photo:
            files = {'photo': photo}
            data = {'chat_id': chat_id}
            if caption:
                data['caption'] = caption
            requests.post(url, data=data, files=files)
    except Exception as e:
        print(f"❌ Ошибка при отправке фото: {e}")

# === Обработка команд Telegram ===
def handle_telegram_command(data):
    print("📨 Получено сообщение:", data)

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip().lower()

    if not chat_id or not text:
        return

    # ✅ Команда старт
    if text in ["/start", "start", "привет", "работаешь?", "ты тут?"]:
        send_telegram_message(chat_id, "🤖 Бот активен и работает 24/7! Напиши /test, /profit или /errors.")

    # ✅ Команда тестового сигнала
    elif text == "/test":
        result = generate_signal()
        signal = result.get("signal")
        rsi = result.get("rsi")
        macd = result.get("macd")
        price = result.get("price")
        patterns = result.get("patterns", [])

        score = evaluate_signal(result)

        # 💾 Логируем как тестовую сделку
        log_test_trade(signal, score, price, rsi, macd)

        caption = (
            f"🧪 Тест сигнала\n"
            f"📊 Сигнал: {signal}\n"
            f"📉 RSI: {rsi:.2f}, 📈 MACD: {macd:.4f}\n"
            f"📌 Паттерны: {', '.join(patterns) if patterns else 'нет'}\n"
            f"🤖 Оценка AI: {score:.2f}\n"
            f"💰 Цена: {price:.2f}"
        )

        if score >= 0.7:
            action = "📈 AL" if signal == "BUY" else "📉 SAT"
            caption += f"\n✅ Рекомендация: {action}"

            image_path = draw_rsi_macd_chart(result)
            if image_path:
                send_telegram_photo(chat_id, image_path, caption)
                return

        send_telegram_message(chat_id, caption)

    # ✅ Команда доходности /profit
    elif text == "/profit":
        path, total_return = generate_profit_chart()

        if path:
            caption = (
                f"💼 Общая доходность: {total_return*100:.2f}%\n"
                f"📈 График: кумулятивная прибыль"
            )
            send_telegram_photo(chat_id, path, caption)
        else:
            send_telegram_message(chat_id, "ℹ️ Недостаточно данных для построения графика прибыли.")

    # ✅ Команда ошибок /errors
    elif text == "/errors":
        summary, explanations = analyze_bad_signals()

        if not summary:
            send_telegram_message(chat_id, "ℹ️ Нет данных об ошибочных сигналах.")
            return

        message = "📉 Анализ ошибочных сигналов:\n"
        for key, value in summary.items():
            message += f"• {key}: {value}\n"

        if explanations:
            message += "\n❗ Примеры ошибок:\n" + "\n".join(explanations)

        send_telegram_message(chat_id, message)

    # 🧠 Умный ответ на некоторые вопросы
    elif "прибыль" in text:
        send_telegram_message(chat_id, "💡 Используй команду /profit для анализа доходности.")
    elif "ошибк" in text:
        send_telegram_message(chat_id, "📉 Введи /errors — покажу, какие сигналы были неудачными.")
    elif "сигнал" in text:
        send_telegram_message(chat_id, "⚡ Попробуй /test — я сгенерирую новый сигнал с графиком и оценкой.")
    else:
        send_telegram_message(chat_id, f"🤖 Неизвестная команда: {text}\nДоступно: /start, /test, /profit, /errors")
