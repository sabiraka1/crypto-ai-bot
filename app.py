import matplotlib
matplotlib.use('Agg')
import os
import re
import logging
import threading
import time
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

# ================== ЗАЩИТА ОТ ДУБЛЕЙ ==================
LOCK_FILE = ".trading.lock"

# Удаляем старый lock при старте контейнера
if os.path.exists(LOCK_FILE):
    try:
        os.remove(LOCK_FILE)
        logger.warning("⚠️ Removed stale lock file: %s", LOCK_FILE)
    except Exception as e:
        logger.error("Ошибка при удалении lock-файла: %s", e)


# ================== ФИЛЬТР ЛОГОВ ==================
class SensitiveDataFilter(logging.Filter):
    SENSITIVE_PATTERN = re.compile(r'(?i)(key|token|secret|password)\s*[:=]\s*["\']?[\w\-:]+["\']?')
    REPLACEMENT = r'\1=***'

    def filter(self, record):
        if record.args and isinstance(record.args, dict):
            record.args = {k: ("***" if any(x in k.lower() for x in ["key", "token", "secret", "password"]) else v)
                           for k, v in record.args.items()}
        if record.msg and isinstance(record.msg, str):
            record.msg = self.SENSITIVE_PATTERN.sub(self.REPLACEMENT, record.msg)
        return True

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
for handler in logging.getLogger().handlers:
    handler.addFilter(SensitiveDataFilter())

def safe_log(data):
    if isinstance(data, dict):
        redacted = {k: ("***" if any(x in k.lower() for x in ["key", "token", "secret", "password"]) else v)
                    for k, v in data.items()}
        logger.info(redacted)
    else:
        logger.info(str(data))

def verify_request():
    if WEBHOOK_SECRET and not request.path.endswith(WEBHOOK_SECRET):
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    if TELEGRAM_SECRET_TOKEN:
        hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if hdr != TELEGRAM_SECRET_TOKEN:
            logger.warning("Webhook: secret token mismatch")
            return jsonify({"ok": False, "error": "unauthorized"}), 403

# ================== ENV ==================
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").rstrip("/")
PORT = int(os.getenv("PORT", 5000))

WEBHOOK_SECRET = (os.getenv("WEBHOOK_SECRET") or "").strip()
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else None
WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}" if (PUBLIC_URL and WEBHOOK_PATH and BOT_TOKEN) else None

TELEGRAM_SECRET_TOKEN = (os.getenv("TELEGRAM_SECRET_TOKEN") or "").strip()
ADMIN_CHAT_IDS = []
_raw_admins = os.getenv("ADMIN_CHAT_IDS", "")
if _raw_admins:
    for x in _raw_admins.replace(",", " ").split():
        try:
            ADMIN_CHAT_IDS.append(int(x))
        except ValueError:
            pass

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN is missing")
if not CHAT_ID:
    logger.warning("⚠️ CHAT_ID is missing — ответы в чат работать не будут")
if not PUBLIC_URL:
    logger.warning("⚠️ PUBLIC_URL is missing — webhook не будет установлен")
if not WEBHOOK_SECRET:
    logger.warning("⚠️ WEBHOOK_SECRET is missing — установите переменную окружения для безопасного вебхука")

ENABLE_WEBHOOK = (os.getenv("ENABLE_WEBHOOK", "1").strip().lower() in ("1", "true", "yes", "on"))
ENABLE_TRADING = (os.getenv("ENABLE_TRADING", "1").strip().lower() in ("1", "true", "yes", "on"))

# ================== FLASK ==================
app = Flask(__name__)

# ================== ГЛОБАЛКИ ==================
_GLOBAL_EX = ExchangeClient()
_STATE = StateManager()
_TRADING_BOT = None  # ✅ Глобальная ссылка на бота
_TRADING_BOT_LOCK = threading.RLock()  # ✅ Блокировка для создания бота

# ================== УТИЛИТЫ ==================
def _train_model_safe() -> bool:
    try:
        import numpy as np
        import pandas as pd
        from analysis.technical_indicators import calculate_all_indicators
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

        df = calculate_all_indicators(df_raw.copy())
        df["price_change"] = df["close"].pct_change()
        df["future_close"] = df["close"].shift(-1)
        df["y"] = (df["future_close"] > df["close"]).astype(int)

        _EPS = 1e-12
        if {"ema_fast", "ema_slow"}.issubset(df.columns):
            df["ema_cross"] = (df["ema_fast"] - df["ema_slow"]) / (df["ema_slow"].abs() + _EPS)
        else:
            df["ema_cross"] = np.nan

        if {"bb_upper", "bb_lower"}.issubset(df.columns):
            rng = (df["bb_upper"] - df["bb_lower"]).abs().replace(0, np.nan) + _EPS
            df["bb_position"] = (df["close"] - df["bb_lower"]) / rng
        else:
            df["bb_position"] = np.nan

        df = df.replace([np.inf, -np.inf], np.nan).dropna()

        feature_cols = [
            "rsi", "macd", "ema_cross", "bb_position",
            "stoch_k", "adx", "volume_ratio", "price_change",
        ]
        if any(c not in df.columns for c in feature_cols) or df.empty:
            logging.error("Not enough features for training")
            return False

        X = df[feature_cols].to_numpy()
        y = df["y"].to_numpy()

        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        df_1d = df_raw.resample("1D").agg(agg)
        df_4h = df_raw.resample("4H").agg(agg)

        analyzer = MultiTimeframeAnalyzer()
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

def _acquire_file_lock(lock_path: str) -> bool:
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False
    except Exception:
        logging.exception("lock create failed")
        return False

# ================== HEALTH ==================
@app.route("/health", methods=["GET"])
@app.route("/healthz", methods=["GET"])
def health():
    return jsonify({"ok": True, "status": "running"}), 200

# ================== DISPATCH (ИСПРАВЛЕННАЯ ВЕРСИЯ) ==================
def _dispatch(text: str, chat_id: Optional[int] = None) -> None:
    """
    ✅ ИСПРАВЛЕНИЕ: Централизованная обработка команд через bot_handler
    """
    if ADMIN_CHAT_IDS and chat_id and int(chat_id) not in ADMIN_CHAT_IDS:
        logging.warning("Unauthorized access denied in dispatch for chat_id=%s", chat_id)
        return

    text = (text or "").strip()
    if not text.startswith("/"):
        return

    try:
        # ✅ ИСПРАВЛЕНИЕ: Передаем корректные объекты, включая _TRADING_BOT для команд
        exchange_client = _GLOBAL_EX
        state_manager = _STATE
        
        # Для команд, которым нужен доступ к боту, проверяем его наличие
        if text.startswith(("/testbuy", "/testsell", "/status")) and _TRADING_BOT:
            # Используем state manager от активного бота если он есть
            state_manager = _TRADING_BOT.state
            exchange_client = _TRADING_BOT.exchange

        # ✅ Используем централизованную обработку команд из bot_handler
        tgbot.process_command(
            text=text, 
            state_manager=state_manager, 
            exchange_client=exchange_client, 
            train_func=_train_model_safe
        )
    except Exception:
        logging.exception("dispatch error")

# ================== WEBHOOK ==================
if ENABLE_WEBHOOK and WEBHOOK_PATH:
    @app.route(WEBHOOK_PATH, methods=["POST"])
    def telegram_webhook():
        try:
            vr = verify_request()
            if vr:
                return vr
            safe_log({'update': 'received'})

            update = request.get_json(silent=True) or {}
            msg = update.get("message") or update.get("edited_message") or {}
            if not msg and update.get("callback_query"):
                msg = update["callback_query"].get("message") or {}

            text = msg.get("text", "")
            chat_id = (msg.get("chat") or {}).get("id")

            if ADMIN_CHAT_IDS and (not chat_id or int(chat_id) not in ADMIN_CHAT_IDS):
                logging.warning("Unauthorized access denied for chat_id=%s", chat_id)
                return jsonify({"ok": True})

            _dispatch(text, chat_id)
        except Exception:
            logging.exception("Webhook handling error")
        return jsonify({"ok": True})
else:
    logger.warning("⚠️ WEBHOOK route not registered: disabled or WEBHOOK_SECRET missing")

def set_webhook():
    if not ENABLE_WEBHOOK:
        logging.info("Webhook disabled by ENABLE_WEBHOOK=0")
        return
    if not (BOT_TOKEN and PUBLIC_URL and WEBHOOK_URL):
        logging.warning("Webhook not set: missing BOT_TOKEN or PUBLIC_URL or WEBHOOK_SECRET")
        return
    if not _acquire_file_lock(".webhook.lock"):
        logging.info("Webhook already initialized by another process")
        return
    logging.info(f"🔗 PUBLIC_URL: {PUBLIC_URL}")
    logging.info(f"📡 Webhook path set to {WEBHOOK_PATH}")
    try:
        params = {"url": WEBHOOK_URL}
        if TELEGRAM_SECRET_TOKEN:
            params["secret_token"] = TELEGRAM_SECRET_TOKEN

        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            params=params,
            timeout=10
        )
        logging.info(f"setWebhook → {r.status_code} {r.text}")
    except Exception:
        logging.exception("setWebhook error")

# ================== TRADING LOOP (ИСПРАВЛЕННАЯ ВЕРСИЯ) ==================
def start_trading_loop():
    """
    ✅ ИСПРАВЛЕНИЕ: Улучшенный запуск торгового цикла с правильной блокировкой
    """
    global _TRADING_BOT
    
    if not ENABLE_TRADING:
        logging.info("Trading loop disabled by ENABLE_TRADING=0")
        return

    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Блокируем создание множественных ботов
    with _TRADING_BOT_LOCK:
        # Проверяем что нет запущенного бота
        if _TRADING_BOT is not None:
            logging.warning("⚠️ Trading bot already initialized, skipping duplicate start")
            return
        
        # Проверяем что нет запущенного потока
        existing_threads = [t for t in threading.enumerate() if t.name == "TradingLoop" and t.is_alive()]
        if existing_threads:
            logging.warning(f"⚠️ Trading loop thread already running: {len(existing_threads)} threads")
            return

        lock_path = ".trading.lock"
        
        # Если лок-файл существует — удаляем, чтобы позволить перезапуск
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
                logging.warning(f"⚠️ Removed stale lock file: {lock_path}")
        except Exception as e:
            logging.error(f"Failed to remove lock file {lock_path}: {e}")

        # Создаём новый лок-файл
        if not _acquire_file_lock(lock_path):
            logging.warning("⚠️ Could not create lock file, but starting trading loop anyway")
        
        # ✅ Создаем глобальный экземпляр бота ТОЛЬКО ОДИН РАЗ
        try:
            _TRADING_BOT = TradingBot()
            logging.info("✅ Trading bot instance created")
        except Exception as e:
            logging.error(f"❌ Failed to create trading bot: {e}")
            return
    
    def trading_loop_wrapper():
        global _TRADING_BOT
        try:
            logging.info("🚀 Trading loop thread starting...")
            _TRADING_BOT.run()
        except Exception as e:
            logging.error(f"❌ Trading loop crashed: {e}")
            # ✅ ИСПРАВЛЕНИЕ: Сбрасываем глобальную переменную при крахе
            with _TRADING_BOT_LOCK:
                _TRADING_BOT = None
            # Попытка перезапуска через 60 секунд
            time.sleep(60)
            logging.info("🔄 Attempting to restart trading loop...")
            start_trading_loop()  # Рекурсивный перезапуск
    
    # Запускаем поток
    t = threading.Thread(target=trading_loop_wrapper, name="TradingLoop", daemon=True)
    t.start()
    logging.info("✅ Trading loop thread started")

# ================== WATCHDOG & MONITORING (ИСПРАВЛЕННАЯ ВЕРСИЯ) ==================
import psutil

def send_telegram_alert(message):
    try:
        if BOT_TOKEN and CHAT_ID:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": message}
            requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logging.error(f"[Telegram Alert Error] {e}")

def monitor_resources():
    try:
        process = psutil.Process(os.getpid())
        mem = process.memory_info().rss / (1024 * 1024)
        cpu = process.cpu_percent(interval=1)
        logging.info(f"[Resources] CPU: {cpu}%, RAM: {mem:.2f} MB")
        
        # Проверяем критические уровни
        if cpu > 80 or mem > (psutil.virtual_memory().total / (1024 * 1024) * 0.8):
            send_telegram_alert(f"⚠️ High usage detected! CPU: {cpu}%, RAM: {mem:.2f} MB")
        return cpu, mem
    except Exception as e:
        logging.error(f"[Resource Monitor] Error: {e}")
        return 0, 0

def watchdog():
    """
    ✅ ИСПРАВЛЕНИЕ: Улучшенный watchdog с правильным мониторингом
    """
    global _TRADING_BOT
    consecutive_failures = 0
    max_failures = 3
    
    while True:
        try:
            monitor_resources()
            
            # Проверяем состояние торгового потока
            trading_thread_alive = any(
                t.name == "TradingLoop" and t.is_alive() 
                for t in threading.enumerate()
            )
            
            # ✅ ИСПРАВЛЕНИЕ: Проверяем что бот существует и поток жив
            bot_exists = _TRADING_BOT is not None
            
            if ENABLE_TRADING and (not trading_thread_alive or not bot_exists):
                consecutive_failures += 1
                status = f"thread_alive={trading_thread_alive}, bot_exists={bot_exists}"
                logging.warning(f"⚠️ Trading system down ({status}), failure #{consecutive_failures}")
                
                if consecutive_failures >= max_failures:
                    send_telegram_alert(f"♻️ Trading system failed {consecutive_failures} times! Attempting restart...")
                    try:
                        # Принудительно сбрасываем бота если он завис
                        with _TRADING_BOT_LOCK:
                            if _TRADING_BOT is not None:
                                logging.warning("🔄 Force resetting hung trading bot")
                                _TRADING_BOT = None
                        
                        start_trading_loop()
                        consecutive_failures = 0  # Сбрасываем счетчик при успешном запуске
                        logging.info("✅ Trading loop restarted by watchdog")
                    except Exception as e:
                        send_telegram_alert(f"❌ Failed to restart trading loop: {e}")
                        logging.error(f"❌ Watchdog restart failed: {e}")
            else:
                consecutive_failures = 0  # Сбрасываем счетчик если все OK
            
            # Проверяем состояние позиций (если бот доступен)
            if _TRADING_BOT and hasattr(_TRADING_BOT, 'state'):
                try:
                    position_state = _TRADING_BOT.state.state
                    if position_state.get("in_position"):
                        last_check = position_state.get("last_manage_check")
                        if last_check:
                            from datetime import datetime, timezone
                            last_dt = datetime.fromisoformat(last_check.replace("Z", "+00:00"))
                            now_dt = datetime.now(timezone.utc)
                            minutes_since = (now_dt - last_dt).total_seconds() / 60
                            
                            # Если позиция не управлялась более 30 минут - предупреждение
                            if minutes_since > 30:
                                logging.warning(f"⚠️ Position not managed for {minutes_since:.1f} minutes")
                                send_telegram_alert(f"⚠️ Позиция не управлялась {minutes_since:.1f} минут")
                                
                except Exception as e:
                    logging.debug(f"Position check error: {e}")
                    
        except Exception as e:
            logging.error(f"[Watchdog] Error: {e}")
        
        time.sleep(300)  # Проверка каждые 5 минут

# Запускаем watchdog в отдельном потоке
threading.Thread(target=watchdog, daemon=True).start()

# ================== KEEP-ALIVE PING ==================
def keep_alive_ping():
    try:
        if PUBLIC_URL:
            requests.get(PUBLIC_URL, timeout=5)
            logging.info(f"[KeepAlive] Pinged {PUBLIC_URL}")
    except Exception as e:
        logging.warning(f"[KeepAlive] Ping failed: {e}")
    
    # Планируем следующий пинг
    threading.Timer(600, keep_alive_ping).start()

# Запускаем keep-alive
keep_alive_ping()

# ================== BOOTSTRAP (ИСПРАВЛЕННАЯ ВЕРСИЯ) ==================
_bootstrapped = False
_bootstrap_lock = threading.RLock()

def _bootstrap_once():
    """
    ✅ ИСПРАВЛЕНИЕ: Безопасная инициализация с проверками
    """
    global _bootstrapped
    
    with _bootstrap_lock:
        if _bootstrapped:
            logging.info("⚠️ Bootstrap already completed, skipping")
            return
            
        try:
            logging.info("🚀 Starting bootstrap process...")
            set_webhook()
        except Exception:
            logging.exception("set_webhook at bootstrap failed")
            
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Запускаем торговый цикл только один раз
            start_trading_loop()
        except Exception:
            logging.exception("start_trading_loop failed")
            
        _bootstrapped = True
        logging.info("✅ Bootstrap completed")

# ================== STARTUP ==================
if __name__ != "__main__":
    _bootstrap_once()

if __name__ == "__main__":
    _bootstrap_once()
    app.run(host="0.0.0.0", port=PORT)