import os
import logging
import threading
from typing import Optional

import requests
from flask import Flask, request, jsonify

# --- наши модули ---
from main import TradingBot
from trading.exchange_client import ExchangeClient
from core.state_manager import StateManager
from telegram import bot_handler as tgbot

# ================== ЛОГИ ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot_activity.log", encoding="utf-8")]
)
logger = logging.getLogger(__name__)

# ================== ENV ==================
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").rstrip("/")
PORT = int(os.getenv("PORT", 5000))

# НОВОЕ: секретный путь вебхука, вместо использования BOT_TOKEN в URL
WEBHOOK_SECRET = (os.getenv("WEBHOOK_SECRET") or "").strip()
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else None
WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}" if (PUBLIC_URL and WEBHOOK_PATH and BOT_TOKEN) else None

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN is missing")
if not CHAT_ID:
    logger.warning("⚠️ CHAT_ID is missing — ответы в чат работать не будут")
if not PUBLIC_URL:
    logger.warning("⚠️ PUBLIC_URL is missing — webhook не будет установлен")
if not WEBHOOK_SECRET:
    logger.warning("⚠️ WEBHOOK_SECRET is missing — установите переменную окружения для безопасного вебхука")

# ================== FLASK ==================
app = Flask(__name__)

# ================== ГЛОБАЛКИ ==================
_GLOBAL_EX = ExchangeClient()          # ccxt клиент (в main.py он тоже создаётся внутри TradingBot)
_STATE = StateManager()                # доступ к bot_state.json и т.п.

# ================== УТИЛИТЫ ==================
def _train_model_safe() -> bool:
    """
    Запуск твоего обучения (по твоей же логике из проекта).
    """
    try:
        import pandas as pd
        from analysis.technical_indicators import TechnicalIndicators
        from analysis.market_analyzer import MultiTimeframeAnalyzer
        from ml.adaptive_model import AdaptiveMLModel

        symbol = os.getenv("SYMBOL", "BTC/USDT")
        timeframe = os.getenv("TIMEFRAME", "15m")

        ohlcv = _GLOBAL_EX.fetch_ohlcv(symbol, timeframe=timeframe, limit=500)
        if not ohlcv:
            logging.error("No OHLCV data for training")
            return False

        cols = ["time", "open", "high", "low", "close", "volume"]
        df_raw = pd.DataFrame(ohlcv, columns=cols)
        df_raw["time"] = pd.to_datetime(df_raw["time"], unit="ms", utc=True)
        df_raw.set_index("time", inplace=True)

        df = TechnicalIndicators.calculate_all_indicators(df_raw.copy())
        df["price_change"] = df["close"].pct_change()
        df["future_close"] = df["close"].shift(-1)
        df["y"] = (df["future_close"] > df["close"]).astype(int)
        df.dropna(inplace=True)

        feature_cols = [
            "rsi", "macd", "ema_cross", "bb_position",
            "stoch_k", "adx", "volume_ratio", "price_change",
        ]
        if any(c not in df.columns for c in feature_cols) or df.empty:
            logging.error("Not enough features for training")
            return False

        X = df[feature_cols].to_numpy()
        y = df["y"].to_numpy()

        analyzer = MultiTimeframeAnalyzer()
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        df_1d = df_raw.resample("1D").agg(agg)
        df_4h = df_raw.resample("4H").agg(agg)

        market_conditions = []
        for idx in df.index:
            cond, _ = analyzer.analyze_market_condition(df_1d.loc[:idx], df_4h.loc[:idx])
            market_conditions.append(cond.value)

        model = AdaptiveMLModel()
        ok = model.train(X, y, market_conditions)
        return bool(ok)
    except Exception:
        logging.exception("train error")
        return False


def _send_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=15
        )
    except Exception:
        logging.exception("sendMessage failed")


# ================== HEALTH ==================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "status": "running"}), 200


# ================== DISPATCH ==================
def _dispatch(text: str, chat_id: Optional[int] = None) -> None:
    """
    Локальный роутер команд. Вызывает только известные команды
    из telegram/bot_handler.py и НЕ отправляет автоответы на неизвестные.
    """
    text = (text or "").strip()
    if not text.startswith("/"):
        return

    try:
        sym = os.getenv("SYMBOL", "BTC/USDT")

        if text.startswith("/start") and hasattr(tgbot, "cmd_start"):
            return tgbot.cmd_start()

        if text.startswith("/status") and hasattr(tgbot, "cmd_status"):
            # отдаём функцию получения последней цены из нашего клиента
            return tgbot.cmd_status(_STATE, lambda: _GLOBAL_EX.get_last_price(sym))

        if text.startswith("/profit") and hasattr(tgbot, "cmd_profit"):
            return tgbot.cmd_profit()

        if text.startswith("/errors") and hasattr(tgbot, "cmd_errors"):
            return tgbot.cmd_errors()

        if text.startswith("/lasttrades") and hasattr(tgbot, "cmd_lasttrades"):
            return tgbot.cmd_lasttrades()

        if text.startswith("/train") and hasattr(tgbot, "cmd_train"):
            return tgbot.cmd_train(_train_model_safe)

        if text.startswith("/testbuy") and hasattr(tgbot, "cmd_testbuy"):
            return tgbot.cmd_testbuy(_STATE, _GLOBAL_EX)

        if text.startswith("/testsell") and hasattr(tgbot, "cmd_testsell"):
            return tgbot.cmd_testsell(_STATE, _GLOBAL_EX)

        if text.startswith("/test") and hasattr(tgbot, "cmd_test"):
            return tgbot.cmd_test()

        # неизвестные команды просто игнорируем (только лог)
        logging.info(f"Ignored unsupported command: {text}")
    except Exception:
        logging.exception("dispatch error")
        # Без автоответа пользователю, как ты просил


# ================== WEBHOOK ==================
# БЫЛО: @app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
# СТАЛО: секретный путь без токена
if WEBHOOK_PATH:
    @app.route(WEBHOOK_PATH, methods=["POST"])
    def telegram_webhook():
        try:
            update = request.get_json(silent=True) or {}
            msg = update.get("message") or update.get("edited_message") or {}
            text = msg.get("text", "")
            chat_id = (msg.get("chat") or {}).get("id")
            _dispatch(text, chat_id)
        except Exception:
            logging.exception("Webhook handling error")
        return jsonify({"ok": True})
else:
    logger.warning("⚠️ WEBHOOK route not registered: WEBHOOK_SECRET is missing")

def set_webhook():
    if not (BOT_TOKEN and PUBLIC_URL and WEBHOOK_URL):
        logging.warning("Webhook not set: missing BOT_TOKEN or PUBLIC_URL or WEBHOOK_SECRET")
        return
    logging.info(f"🔗 PUBLIC_URL: {PUBLIC_URL}")
    # НЕ печатаем токен и полный URL
    logging.info(f"📡 Webhook path set to {WEBHOOK_PATH}")
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            params={"url": WEBHOOK_URL},
            timeout=10
        )
        logging.info(f"setWebhook → {r.status_code} {r.text}")
    except Exception:
        logging.exception("setWebhook error")


# ================== TRADING LOOP ==================
def start_trading_loop():
    bot = TradingBot()  # твой реальный торговый бот из main.py
    t = threading.Thread(target=bot.run, name="trading-loop", daemon=True)
    t.start()
    logging.info("Trading loop thread started")


# ================== ENTRYPOINT ==================
if __name__ == "__main__":
    set_webhook()
    start_trading_loop()
    app.run(host="0.0.0.0", port=PORT)
