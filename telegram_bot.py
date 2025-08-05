import requests
import os
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal, draw_rsi_macd_chart
from data_logger import log_test_trade

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f: {e}")

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
        print(f"\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0435 \u0444\u043e\u0442\u043e: {e}")

def handle_telegram_command(data):
    print("\ud83d\udce8 \u041f\u043e\u043b\u0443\u0447\u0435\u043d\u043e \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435:", data)

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id or not text:
        return

    if text.lower() in ["/start", "start"]:
        send_telegram_message(chat_id, "🤖 \u0411\u043e\u0442 \u0430\u043a\u0442\u0438\u0432\u0435\u043d \u0438 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442 24/7!")

    elif "/test" in text.lower():
        result = generate_signal()
        signal = result["signal"]
        rsi = result["rsi"]
        macd = result["macd"]
        price = result["price"]
        patterns = result.get("patterns", [])

        score = evaluate_signal(result)
        log_test_trade(signal, score, price)

        caption = (
            f"🧪 \u0422\u0435\u0441\u0442 \u0441\u0438\u0433\u043d\u0430\u043b\u0430\n"
            f"📊 \u0421\u0438\u0433\u043d\u0430\u043b: {signal}\n"
            f"📉 RSI: {rsi}, 📈 MACD: {macd}\n"
            f"📌 \u041f\u0430\u0442\u0442\u0435\u0440\u043d\u044b: {', '.join(patterns) if patterns else 'нет'}\n"
            f"�\udd16 \u041e\u0446\u0435\u043d\u043a\u0430 AI: {score:.2f}\n"
            f"�\udcb0 \u0426\u0435\u043d\u0430: {price}"
        )

        if score >= 0.7:
            action = "📈 AL" if signal == "BUY" else "📉 SAT"
            caption += f"\n\u2705 \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f: {action}"

            image_path = draw_rsi_macd_chart(result)
            if image_path:
                send_telegram_photo(chat_id, image_path, caption)
                return

        send_telegram_message(chat_id, caption)

    else:
        send_telegram_message(chat_id, f"📨 \u0412\u044b \u043d\u0430\u043f\u0438\u0441\u0430\u043b\u0438: {text}")
