import os
import logging
import threading
from flask import Flask, request, jsonify

from main import TradingBot
from core.state_manager import StateManager
from trading.exchange_client import ExchangeClient
from telegram.bot_handler import (
    cmd_start, cmd_status, cmd_profit, cmd_errors, cmd_lasttrades, cmd_train, cmd_test, cmd_testbuy, cmd_testsell
)

# --- тихий /train: не падаем, если нужны X/y ---
def _train_model_safe():
    try:
        from ml.adaptive_model import AdaptiveMLModel
        AdaptiveMLModel().train()
        return True
    except Exception as e:
        logging.error("train error: %s", e)
        return False

# --- логирование ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_activity.log", encoding="utf-8"),
    ],
)

app = Flask(__name__)

# --- единый ExchangeClient (singleton для процесса) ---
_GLOBAL_EX = ExchangeClient()

# --- домашняя страница/health ---
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "status": "running"}), 200

@app.route("/", methods=["GET"])
def home():
    return "Crypto AI Bot: OK", 200

# --- Telegram webhook ---
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True) or {}
        msg = (data.get("message") or data.get("edited_message") or {}) or {}
        text = (msg.get("text") or "").strip()
        if not text:
            return jsonify({"ok": True}), 200

        state = StateManager()
        ex = _GLOBAL_EX
        symbol = os.getenv("SYMBOL", "BTC/USDT")

        logging.info(f"📩 Received command: {text}")

        if text in ("/start", "start", "/help", "help"):
            cmd_start()

        elif text in ("/status", "status"):
            cmd_status(state, lambda: ex.ticker(symbol).get("last"))

        elif text in ("/profit", "profit"):
            cmd_profit()

        elif text in ("/errors", "errors"):
            cmd_errors()

        elif text in ("/lasttrades", "lasttrades"):
            cmd_lasttrades()

        elif text in ("/train", "train"):
            cmd_train(_train_model_safe)

        elif text in ("/test", "test"):
            cmd_test(symbol)

        elif text in ("/testbuy", "testbuy"):
            cmd_testbuy(state, ex, symbol=symbol)

        elif text in ("/testsell", "testsell"):
            cmd_testsell(state, ex, symbol=symbol)

        else:
            logging.info(f"⚠️ Unknown command ignored: {text}")

        return jsonify({"ok": True}), 200

    except Exception as e:
        logging.exception("webhook error")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
