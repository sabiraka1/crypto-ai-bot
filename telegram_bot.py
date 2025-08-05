import os
import requests
from flask import request
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_telegram_message(message):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

# 👇 Новое: обработка команд
def handle_telegram_command(data):
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if text == "/start":
        send_telegram_message("👋 Привет! Я готов присылать тебе сигналы.")
    elif text == "/status":
        send_telegram_message("🤖 Бот работает. Ждёт сигналы от RSI и MACD.")
    elif text == "/help":
        send_telegram_message("ℹ️ Доступные команды:\n/start — запуск\n/status — статус\n/help — помощь")
    else:
        send_telegram_message("❓ Неизвестная команда. Напиши /help")
