import os
import logging
import threading
from flask import Flask, request, jsonify
import requests

# ================== ЛОГИ ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # Без / в конце
PORT = int(os.getenv("PORT", 5000))

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN is missing in environment variables!")
if not PUBLIC_URL:
    logger.error("❌ PUBLIC_URL is missing in environment variables!")

WEBHOOK_URL = f"{PUBLIC_URL}/webhook/{BOT_TOKEN}" if BOT_TOKEN and PUBLIC_URL else None

# ================== FLASK ==================
app = Flask(__name__)

# ================== TELEGRAM ОТПРАВКА ==================
def send_message(text):
    """Отправка сообщения в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        r = requests.post(url, json=payload)
        if r.status_code != 200:
            logger.error(f"❌ Telegram sendMessage error: {r.text}")
    except Exception as e:
        logger.error(f"❌ Telegram send error: {e}")

# ================== WEBHOOK ==================
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    """Обработка входящих обновлений Telegram"""
    try:
        data = request.get_json()

        if not data or "message" not in data:
            return jsonify({"ok": True})

        message = data["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        logger.info(f"📩 Incoming message: {text}")

        # ==== Обработка команд ====
        if text == "/start":
            send_message("🤖 Бот запущен и готов к работе!")
        elif text == "/test":
            send_message("🧪 Тестовый сигнал отправлен!")
        elif text == "/train":
            send_message("📚 Запускаю обучение модели...")
        elif text == "/profit":
            send_message("💰 Прибыль за период: 0 USDT")
        elif text == "/errors":
            send_message("⚠️ Ошибки сигналов: пока нет данных")
        elif text == "/status":
            send_message("📊 Открытых позиций нет")
        else:
            # Просто игнорируем неизвестные команды, без лишних сообщений
            logger.info(f"ℹ️ Команда {text} не поддерживается, пропущено.")
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return jsonify({"ok": False}), 500

# ================== УСТАНОВКА WEBHOOK ==================
def set_webhook():
    if BOT_TOKEN and PUBLIC_URL:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        payload = {"url": WEBHOOK_URL}
        try:
            r = requests.post(url, json=payload)
            logger.info(f"setWebhook → {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"❌ setWebhook error: {e}")
    else:
        logger.warning("⚠️ Webhook not set: BOT_TOKEN or PUBLIC_URL is missing")

# ================== ЗАПУСК БОТА ==================
def start_trading_loop():
    """Имитация работы торгового цикла"""
    def loop():
        logger.info("🔄 Trading loop started...")
        # Здесь твоя логика трейдинга
    threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    set_webhook()
    start_trading_loop()
    app.run(host="0.0.0.0", port=PORT)
