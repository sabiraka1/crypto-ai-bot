import os
import logging
import threading
from flask import Flask, request, jsonify

# важно: у тебя в main.py класс называется TradingBot (не CryptoBot)
from main import TradingBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_activity.log", encoding="utf-8")
    ],
)

app = Flask(__name__)

# --- запустим бота в фоновом потоке ---
_bot_instance = TradingBot()

def _run_bot():
    try:
        logging.info("🚀 Trading bot starting...")
        _bot_instance.run()
    except Exception:
        logging.exception("Trading bot crashed")

threading.Thread(target=_run_bot, daemon=True).start()

# --- healthcheck для Render ---
@app.route("/alive", methods=["GET"])
def alive():
    return jsonify({"ok": True, "status": "running"}), 200

# --- Telegram webhook (опционально, если захочешь команды на вебхуке) ---
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True) or {}
        msg = (data.get("message") or data.get("edited_message") or {})
        text = (msg.get("text") or "").strip()
        # Пример простого роутинга команд (если нужно):
        # from telegram.bot_handler import cmd_status, cmd_profit, cmd_errors, cmd_lasttrades, cmd_train
        # from core.state_manager import StateManager
        # from trading.exchange_client import ExchangeClient
        # if text == "/status":
        #     state = StateManager()
        #     ex = ExchangeClient(api_key=os.getenv("GATE_API_KEY"), api_secret=os.getenv("GATE_API_SECRET"))
        #     cmd_status(state, lambda: ex.ticker(os.getenv("SYMBOL", "BTC/USDT")).get("last"))
        # elif text == "/profit":
        #     cmd_profit()
        # ...
        return jsonify({"ok": True}), 200
    except Exception as e:
        logging.exception("webhook error")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
