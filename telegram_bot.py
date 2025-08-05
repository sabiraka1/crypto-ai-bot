import requests

BOT_TOKEN = "8234706353:AAFzjno5FcYta2MMOq57RFgaT6zF9bbI2UU"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    return requests.post(url, json=payload)

def handle_telegram_command(data):
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if text and chat_id:
        if text.lower() in ["/start", "start"]:
            send_telegram_message(chat_id, "🤖 Бот активен! Готов к работе.")
        else:
            send_telegram_message(chat_id, f"📨 Вы написали: {text}")
