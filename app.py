import os
import logging
import threading
import requests
from flask import Flask, request, jsonify

from main import TradingBot
from trading.exchange_client import ExchangeClient

# Безопасно импортируем весь модуль, а не конкретные именованные cmd_*
# чтобы не падать, если каких-то команд нет.
from telegram import bot_handler as tgbot

# === Тихая тренировка модели (оставлено из оригинала) =========================
def _train_model_safe() -> bool:
    try:
        import pandas as pd
        from analysis.technical_indicators import TechnicalIndicators
        from analysis.market_analyzer import MultiTimeframeAnalyzer
        from ml.adaptive_model import AdaptiveMLModel

        symbol = os.getenv("SYMBOL", "BTC/USDT")
        timeframe = os.getenv("TIMEFRAME", "15m")

        ex = _GLOBAL_EX  # см. ниже

        # Исторические данные
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=500)
        if not ohlcv:
            logging.error("No OHLCV data for training")
            return False

        cols = ["time", "open", "high", "low", "close", "volume"]
        df_raw = pd.DataFrame(ohlcv, columns=cols)
        df_raw["time"] = pd.to_datetime(df_raw["time"], unit="ms", utc=True)
        df_raw.set_index("time", inplace=True)

        # Индикаторы
        df = TechnicalIndicators.calculate_all_indicators(df_raw.copy())
        df["price_change"] = df["close"].pct_change()
        df["future_close"] = df["close"].shift(-1)
        df["y"] = (df["future_close"] > df["close"]).astype(int)
        df.dropna(inplace=True)

        feature_cols = [
            "rsi", "macd", "ema_cross", "bb_position",
            "stoch_k", "adx", "volume_ratio", "price_change",
        ]
        if any(col not in df.columns for col in feature_cols) or df.empty:
            logging.error("Not enough features for training")
            return False

        X = df[feature_cols].to_numpy()
        y = df["y"].to_numpy()

        # Рыночные условия
        analyzer = MultiTimeframeAnalyzer()
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        df_1d = df_raw.resample("1D").agg(agg)
        df_4h = df_raw.resample("4H").agg(agg)

        market_conditions: list[str] = []
        for idx in df.index:
            cond, _ = analyzer.analyze_market_condition(df_1d.loc[:idx], df_4h.loc[:idx])
            market_conditions.append(cond.value)

        model = AdaptiveMLModel()
        return model.train(X, y, market_conditions)
    except Exception as e:
        logging.error("train error: %s", e)
        return False

# === Логи =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_activity.log", encoding="utf-8"),
    ],
)

app = Flask(__name__)

# === Глобальный ExchangeClient (singleton) ====================================
_GLOBAL_EX = ExchangeClient()

# === Healthcheck ==============================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "status": "running"}), 200

# === Webhook для Telegram =====================================================
def _dispatch_command(text: str):
    """
    Простейший роутер команд. Поддержаны те, что реально есть в telegram/bot_handler.py:
    - /test
    - /testbuy
    - /testsell
    Остальные игнорируем, но не падаем.
    """
    try:
        text = (text or "").strip()
        if not text.startswith("/"):
            return

        # Достаём функции безопасно (если их нет — вернётся None)
        cmd_test = getattr(tgbot, "cmd_test", None)
        cmd_testbuy = getattr(tgbot, "cmd_testbuy", None)
        cmd_testsell = getattr(tgbot, "cmd_testsell", None)

        if text.startswith("/test") and cmd_test:
            cmd_test()
        elif text.startswith("/testbuy") and cmd_testbuy:
            cmd_testbuy()
        elif text.startswith("/testsell") and cmd_testsell:
            cmd_testsell()
        else:
            logging.info(f"Unknown or unsupported command: {text}")
    except Exception as e:
        logging.exception(f"Command dispatch error: {e}")

@app.route(f"/webhook/{os.getenv('BOT_TOKEN', 'token-not-set')}", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(silent=True) or {}
        message = update.get("message") or update.get("edited_message") or {}
        text = message.get("text", "")
        _dispatch_command(text)
    except Exception as e:
        logging.exception(f"Webhook handling error: {e}")
    return jsonify({"ok": True})

def set_webhook():
    token = os.getenv("BOT_TOKEN")
    public_url = os.getenv("PUBLIC_URL", "").rstrip("/")
    if not token or not public_url:
        logging.warning("Webhook not set: BOT_TOKEN or PUBLIC_URL is missing")
        return

    url = f"{public_url}/webhook/{token}"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook", params={"url": url}, timeout=10)
        logging.info(f"setWebhook → {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"setWebhook error: {e}")

# === Старт фонового торгового цикла ==========================================
def start_trading_loop():
    bot = TradingBot()
    t = threading.Thread(target=bot.run, name="trading-loop", daemon=True)
    t.start()
    logging.info("Trading loop thread started")

# === Точка входа для Railway ==================================================
if __name__ == "__main__":
    # 1) ставим webhook (если PUBLIC_URL указан)
    set_webhook()

    # 2) запускаем торговый цикл в фоне
    start_trading_loop()

    # 3) поднимаем Flask, чтобы Railway видел открытый порт
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
