import os
import logging
import threading
from flask import Flask, request, jsonify

from main import TradingBot
from core.state_manager import StateManager
from trading.exchange_client import ExchangeClient
from telegram.bot_handler import (
    cmd_start, cmd_status, cmd_profit, cmd_errors, cmd_lasttrades, cmd_train
)

# опциональная интеграция обучения
def _train_model_safe():
    try:
        from ml.adaptive_model import AdaptiveMLModel
        m = AdaptiveMLModel()
        try:
            m.train()
        except AttributeError:
            # если метод называется иначе
            if hasattr(m, "fit"):
                m.fit()
    except Exception as e:
        logging.error(f"Train model error: {e}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot_activity.log", encoding="utf-8")],
)

app = Flask(__name__)

# --- запустим торгового бота в фоновом потоке ---
_bot_instance = TradingBot()
def _run_bot():
    try:
        logging.info("🚀 Trading bot starting...")
        _bot_instance.run()
    except Exception:
        logging.exception("Trading bot crashed")
threading.Thread(target=_run_bot, daemon=True).start()

@app.route("/alive", methods=["GET"])
def alive():
    return jsonify({"ok": True, "status": "running"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True) or {}
        msg = (data.get("message") or data.get("edited_message") or {}) or {}
        text = (msg.get("text") or "").strip()

        if not text:
            return jsonify({"ok": True}), 200

        # подготовим зависимости для команд
        state = StateManager()
        ex = ExchangeClient(api_key=os.getenv("GATE_API_KEY"), api_secret=os.getenv("GATE_API_SECRET"))
        symbol = os.getenv("SYMBOL", "BTC/USDT")

        # простой роутинг
        if text in ("/start", "start"):
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

        else:
            # необязательный эхо / help
            if text == "/help":
                cmd_start()
            else:
                # игнор прочего текста
                pass

        return jsonify({"ok": True}), 200
    except Exception as e:
        logging.exception("webhook error")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
