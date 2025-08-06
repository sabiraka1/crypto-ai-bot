import os
import requests
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from grafik_olusturucu import draw_rsi_macd_chart
from profit_chart import generate_profit_chart  # 📊 График доходности
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
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return

    # ✅ Команда старт
    if text.lower() in ["/start", "start"]:
        send_telegram_message(chat_id, "🤖 Бот активен и работает 24/7!")

    # ✅ Команда тестового сигнала
    elif text.lower() == "/test":
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
    elif text.lower() == "/profit":
        image_path = generate_profit_chart()
        if image_path:
            send_telegram_photo(chat_id, image_path, "📈 Кумулятивная доходность")
        else:
            send_telegram_message(chat_id, "❌ График доходности не удалось сгенерировать.")

    # ❓ Любая другая команда
    else:
        send_telegram_message(chat_id, f"📨 Вы написали: {text}")
