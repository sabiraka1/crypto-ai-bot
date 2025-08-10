import matplotlib
matplotlib.use('Agg')
import os
import re
import logging
import threading
import time
import atexit
from typing import Optional
import requests
from flask import Flask, request, jsonify

# --- наши модули ---
from main import TradingBot
from trading.exchange_client import ExchangeClient
from core.state_manager import StateManager
from telegram import bot_handler as tgbot
from config.settings import TradingConfig

# ================== ЛОГИ ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot_activity.log", encoding="utf-8")]
)
logger = logging.getLogger(__name__)

# ================== КОНФИГУРАЦИЯ ==================
CFG = TradingConfig()

# Валидация при запуске
config_errors = CFG.validate_config()
if config_errors:
    logger.warning("⚠️ Configuration issues found:")
    for error in config_errors:
        logger.warning(f"  - {error}")

# ================== ЗАЩИТА ОТ ДУБЛЕЙ ==================
LOCK_FILE = ".trading.lock"
WEBHOOK_LOCK_FILE = ".webhook.lock"

# Удаляем старые lock при старте контейнера
for lock_file in [LOCK_FILE, WEBHOOK_LOCK_FILE]:
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            logger.warning("⚠️ Removed stale lock file: %s", lock_file)
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

# Применяем фильтр
for handler in logging.getLogger().handlers:
    handler.addFilter(SensitiveDataFilter())

# ================== FLASK ==================
app = Flask(__name__)

# ================== ГЛОБАЛКИ ==================
_GLOBAL_EX = ExchangeClient(
    api_key=CFG.GATE_API_KEY,
    api_secret=CFG.GATE_API_SECRET,
    safe_mode=CFG.SAFE_MODE
)
_STATE = StateManager()
_TRADING_BOT = None  # ✅ Глобальная ссылка на бота
_TRADING_BOT_LOCK = threading.RLock()  # ✅ Блокировка для создания бота
_WATCHDOG_THREAD = None
_BOOTSTRAP_DONE = False

# ================== WEBHOOK SECURITY ==================
def verify_request():
    """Проверка безопасности webhook запроса"""
    # Проверка секрета в URL
    if CFG.WEBHOOK_SECRET and not request.path.endswith(CFG.WEBHOOK_SECRET):
        return jsonify({"ok": False, "error": "unauthorized"}), 403
        
    # Проверка Telegram secret token
    if CFG.TELEGRAM_SECRET_TOKEN:
        hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if hdr != CFG.TELEGRAM_SECRET_TOKEN:
            logger.warning("Webhook: secret token mismatch")
            return jsonify({"ok": False, "error": "unauthorized"}), 403
    
    return None

# ================== УТИЛИТЫ ==================
def _train_model_safe() -> bool:
    """Безопасное обучение модели"""
    try:
        import numpy as np
        import pandas as pd
        from analysis.technical_indicators import calculate_all_indicators
        from analysis.market_analyzer import MultiTimeframeAnalyzer
        from ml.adaptive_model import AdaptiveMLModel

        symbol = CFG.SYMBOL
        timeframe = CFG.TIMEFRAME

        ohlcv = _GLOBAL_EX.fetch_ohlcv(symbol, timeframe=timeframe, limit=500)
        if not ohlcv:
            logging.error("No OHLCV data for training")
            return False

        cols = ["time", "open", "high", "low", "close", "volume"]
        df_raw = pd.DataFrame(ohlcv, columns=cols)
        df_raw["time"] = pd.to_datetime(df_raw["time"], unit="ms", utc=True)
        df_raw.set_index("time", inplace=True)

        # Расчет индикаторов
        df = calculate_all_indicators(df_raw.copy())
        df["price_change"] = df["close"].pct_change()
        df["future_close"] = df["close"].shift(-1)
        df["y"] = (df["future_close"] > df["close"]).astype(int)

        # Дополнительные фичи
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

        # Подготовка рыночных условий
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        df_1d = df_raw.resample("1D").agg(agg)
        df_4h = df_raw.resample("4H").agg(agg)

        analyzer = MultiTimeframeAnalyzer()
        market_conditions = []
        for idx in df.index:
            cond, _ = analyzer.analyze_market_condition(df_1d.loc[:idx], df_4h.loc[:idx])
            market_conditions.append(cond.value)

        # Обучение модели
        model = AdaptiveMLModel(models_dir=CFG.MODEL_DIR)
        ok = model.train(X, y, market_conditions)
        return bool(ok)

    except Exception:
        logging.exception("Training error")
        return False

def _send_message(text: str) -> None:
    """Отправка сообщения в Telegram"""
    try:
        tgbot.send_message(text)
    except Exception:
        logging.exception("Failed to send Telegram message")

def _acquire_file_lock(lock_path: str) -> bool:
    """Создание файловой блокировки"""
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False
    except Exception:
        logging.exception("Lock create failed")
        return False

# ================== HEALTH ==================
@app.route("/health", methods=["GET"])
@app.route("/healthz", methods=["GET"])
def health():
    """Health check endpoint"""
    status = {
        "ok": True,
        "status": "running",
        "trading_bot_active": _TRADING_BOT is not None,
        "safe_mode": CFG.SAFE_MODE,
        "webhook_enabled": CFG.ENABLE_WEBHOOK,
        "trading_enabled": CFG.ENABLE_TRADING,
        "bootstrap_done": _BOOTSTRAP_DONE
    }
    
    # Проверяем состояние торгового бота
    if _TRADING_BOT:
        try:
            position_active = _TRADING_BOT._is_position_active()
            status["position_active"] = position_active
        except:
            status["position_active"] = "unknown"
    
    return jsonify(status), 200

# ================== DISPATCH (ИСПРАВЛЕННАЯ ВЕРСИЯ) ==================
def _dispatch(text: str, chat_id: Optional[str] = None) -> None:
    """
    ✅ ИСПРАВЛЕНИЕ: Централизованная обработка команд с правильной авторизацией
    """
    
    # Проверка авторизации
    if chat_id and not CFG.is_admin(chat_id):
        logger.warning("Unauthorized access denied for chat_id=%s", chat_id)
        tgbot.send_message("❌ У вас нет прав для выполнения команд.", chat_id=chat_id)
        return

    text = (text or "").strip()
    if not text.startswith("/"):
        return

    try:
        # ✅ ИСПРАВЛЕНИЕ: Передаем корректные объекты
        exchange_client = _GLOBAL_EX
        state_manager = _STATE
        
        # Для команд, которым нужен доступ к боту, используем его state manager
        if text.startswith(("/testbuy", "/testsell", "/status")) and _TRADING_BOT:
            state_manager = _TRADING_BOT.state
            exchange_client = _TRADING_BOT.exchange

        # ✅ Используем централизованную обработку команд из bot_handler
        tgbot.process_command(
            text=text, 
            state_manager=state_manager, 
            exchange_client=exchange_client, 
            train_func=_train_model_safe,
            chat_id=chat_id
        )
    except Exception:
        logging.exception("Dispatch error")

# ================== WEBHOOK ==================
if CFG.ENABLE_WEBHOOK and CFG.WEBHOOK_SECRET:
    webhook_path = f"/webhook/{CFG.WEBHOOK_SECRET}"
    
    @app.route(webhook_path, methods=["POST"])
    def telegram_webhook():
        """Webhook для получения обновлений от Telegram"""
        try:
            # Проверка безопасности
            verification_result = verify_request()
            if verification_result:
                return verification_result
            
            logger.debug('Webhook received')

            # Парсинг обновления
            update = request.get_json(silent=True) or {}
            
            # Извлечение сообщения
            msg = update.get("message") or update.get("edited_message")
            if not msg and update.get("callback_query"):
                msg = update["callback_query"].get("message") or {}

            if not msg:
                return jsonify({"ok": True})

            text = msg.get("text", "")
            chat_info = msg.get("chat") or {}
            chat_id = str(chat_info.get("id", ""))

            if not text or not chat_id:
                return jsonify({"ok": True})

            # Обработка команды
            _dispatch(text, chat_id)
            
        except Exception:
            logging.exception("Webhook handling error")
            
        return jsonify({"ok": True})
else:
    logger.warning("⚠️ WEBHOOK not registered: disabled or WEBHOOK_SECRET missing")

def set_webhook():
    """Установка webhook в Telegram"""
    if not CFG.ENABLE_WEBHOOK:
        logging.info("Webhook disabled by ENABLE_WEBHOOK=0")
        return
        
    webhook_url = CFG.get_webhook_url()
    if not webhook_url:
        logging.warning("Webhook not set: missing configuration")
        return
        
    if not _acquire_file_lock(WEBHOOK_LOCK_FILE):
        logging.info("Webhook already initialized by another process")
        return
        
    logging.info(f"🔗 Setting webhook: {CFG.PUBLIC_URL}")
    
    try:
        params = {"url": webhook_url}
        if CFG.TELEGRAM_SECRET_TOKEN:
            params["secret_token"] = CFG.TELEGRAM_SECRET_TOKEN

        api_url = f"https://api.telegram.org/bot{CFG.BOT_TOKEN}/setWebhook"
        r = requests.post(api_url, params=params, timeout=10)
        
        logging.info(f"setWebhook → {r.status_code} {r.text}")
        
        if r.status_code == 200:
            _send_message("🔗 Webhook установлен успешно")
        else:
            logging.error(f"Webhook setup failed: {r.text}")
            
    except Exception:
        logging.exception("setWebhook error")

# ================== TRADING LOOP (ДЛЯ GUNICORN) ==================
def start_trading_loop():
    """
    ✅ GUNICORN VERSION: Запуск торгового цикла для Gunicorn
    """
    global _TRADING_BOT
    
    if not CFG.ENABLE_TRADING:
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

        lock_path = LOCK_FILE
        
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
            _send_message("🚀 Торговый бот запущен успешно!")
        except Exception as e:
            logging.error(f"❌ Failed to create trading bot: {e}")
            _send_message(f"❌ Ошибка запуска торгового бота: {e}")
            return
    
    def trading_loop_wrapper():
        """Обертка для торгового цикла с обработкой ошибок"""
        global _TRADING_BOT
        try:
            logging.info("🚀 Trading loop thread starting...")
            _TRADING_BOT.run()
        except Exception as e:
            logging.error(f"❌ Trading loop crashed: {e}")
            _send_message(f"❌ Торговый цикл остановлен: {e}")
            
            # ✅ ИСПРАВЛЕНИЕ: Сбрасываем глобальную переменную при крахе
            with _TRADING_BOT_LOCK:
                _TRADING_BOT = None
                
            # Попытка перезапуска через 60 секунд
            time.sleep(60)
            logging.info("🔄 Attempting to restart trading loop...")
            start_trading_loop()  # Рекурсивный перезапуск
    
    # ✅ GUNICORN: Запускаем поток как daemon для правильного завершения
    t = threading.Thread(target=trading_loop_wrapper, name="TradingLoop", daemon=True)
    t.start()
    logging.info("✅ Trading loop thread started")

# ================== WATCHDOG & MONITORING ==================
import psutil

def send_telegram_alert(message):
    """Отправка критических уведомлений"""
    try:
        _send_message(f"🚨 {message}")
    except Exception as e:
        logging.error(f"[Telegram Alert Error] {e}")

def monitor_resources():
    """Мониторинг ресурсов системы"""
    try:
        process = psutil.Process(os.getpid())
        mem_mb = process.memory_info().rss / (1024 * 1024)
        cpu_pct = process.cpu_percent(interval=1)
        
        logging.debug(f"[Resources] CPU: {cpu_pct:.1f}%, RAM: {mem_mb:.1f} MB")
        
        # Проверяем критические уровни
        total_memory_mb = psutil.virtual_memory().total / (1024 * 1024)
        memory_threshold = total_memory_mb * 0.8
        
        if cpu_pct > 85 or mem_mb > memory_threshold:
            send_telegram_alert(f"High resource usage! CPU: {cpu_pct:.1f}%, RAM: {mem_mb:.1f} MB")
            
        return cpu_pct, mem_mb
    except Exception as e:
        logging.error(f"[Resource Monitor] Error: {e}")
        return 0, 0

def watchdog():
    """
    ✅ GUNICORN VERSION: Улучшенный watchdog
    """
    global _TRADING_BOT
    consecutive_failures = 0
    max_failures = 3
    
    while True:
        try:
            # Мониторинг ресурсов
            monitor_resources()
            
            # Проверяем состояние торгового потока
            trading_thread_alive = any(
                t.name == "TradingLoop" and t.is_alive() 
                for t in threading.enumerate()
            )
            
            # ✅ ИСПРАВЛЕНИЕ: Проверяем что бот существует и поток жив
            bot_exists = _TRADING_BOT is not None
            
            if CFG.ENABLE_TRADING and (not trading_thread_alive or not bot_exists):
                consecutive_failures += 1
                status = f"thread_alive={trading_thread_alive}, bot_exists={bot_exists}"
                logging.warning(f"⚠️ Trading system down ({status}), failure #{consecutive_failures}")
                
                if consecutive_failures >= max_failures:
                    send_telegram_alert(f"Trading system failed {consecutive_failures} times! Attempting restart...")
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
                        send_telegram_alert(f"Failed to restart trading loop: {e}")
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
                                send_telegram_alert(f"Position not managed for {minutes_since:.1f} minutes")
                                
                except Exception as e:
                    logging.debug(f"Position check error: {e}")
                    
        except Exception as e:
            logging.error(f"[Watchdog] Error: {e}")
        
        time.sleep(300)  # Проверка каждые 5 минут

# ================== BOOTSTRAP (ДЛЯ GUNICORN) ==================
def _bootstrap_once():
    """
    ✅ GUNICORN VERSION: Безопасная инициализация для Gunicorn
    """
    global _BOOTSTRAP_DONE, _WATCHDOG_THREAD
    
    if _BOOTSTRAP_DONE:
        logging.info("⚠️ Bootstrap already completed, skipping")
        return
        
    try:
        logging.info("🚀 Starting Gunicorn bootstrap process...")
        
        # Проверяем конфигурацию
        if config_errors:
            _send_message(f"⚠️ Configuration issues detected:\n" + "\n".join(config_errors[:3]))
        
        # Устанавливаем webhook
        if CFG.ENABLE_WEBHOOK:
            set_webhook()
    except Exception:
        logging.exception("set_webhook at bootstrap failed")
        
    try:
        # ✅ GUNICORN: Запускаем торговый цикл только один раз
        if CFG.ENABLE_TRADING:
            start_trading_loop()
    except Exception:
        logging.exception("start_trading_loop failed")
        
    try:
        # ✅ GUNICORN: Запускаем watchdog как daemon thread
        if not _WATCHDOG_THREAD or not _WATCHDOG_THREAD.is_alive():
            _WATCHDOG_THREAD = threading.Thread(target=watchdog, daemon=True, name="Watchdog")
            _WATCHDOG_THREAD.start()
            logging.info("✅ Watchdog started")
    except Exception:
        logging.exception("watchdog start failed")
        
    _BOOTSTRAP_DONE = True
    logging.info("✅ Gunicorn bootstrap completed successfully")
    
    # Уведомляем о запуске
    try:
        status_msg = [
            "🚀 Торговый бот запущен на Gunicorn!",
            f"📊 Символ: {CFG.SYMBOL}",
            f"⏰ Таймфрейм: {CFG.TIMEFRAME}",
            f"💰 Размер позиции: ${CFG.POSITION_SIZE_USD}",
            f"🛡️ Безопасный режим: {'ON' if CFG.SAFE_MODE else 'OFF'}",
            f"🤖 AI включен: {'YES' if CFG.AI_ENABLE else 'NO'}",
            "",
            "Используйте /help для списка команд"
        ]
        _send_message("\n".join(status_msg))
    except Exception:
        pass

# ================== ДОПОЛНИТЕЛЬНЫЕ ENDPOINTS ==================
@app.route("/status", methods=["GET"])
def status_endpoint():
    """Детальный статус системы"""
    try:
        status = {
            "timestamp": time.time(),
            "config": {
                "symbol": CFG.SYMBOL,
                "timeframe": CFG.TIMEFRAME,
                "safe_mode": CFG.SAFE_MODE,
                "ai_enabled": CFG.AI_ENABLE,
                "webhook_enabled": CFG.ENABLE_WEBHOOK,
                "trading_enabled": CFG.ENABLE_TRADING
            },
            "trading_bot": {
                "initialized": _TRADING_BOT is not None,
                "thread_alive": any(t.name == "TradingLoop" and t.is_alive() for t in threading.enumerate())
            }
        }
        
        # Информация о позиции
        if _TRADING_BOT:
            try:
                status["position"] = _TRADING_BOT.pm.get_position_summary()
            except:
                status["position"] = {"error": "failed_to_get_summary"}
        
        # Ресурсы
        try:
            cpu, mem = monitor_resources()
            status["resources"] = {"cpu_percent": cpu, "memory_mb": mem}
        except:
            status["resources"] = {"error": "failed_to_get_resources"}
            
        return jsonify(status)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/force_restart", methods=["POST"])
def force_restart():
    """Принудительный перезапуск торгового бота"""
    global _TRADING_BOT
    
    try:
        with _TRADING_BOT_LOCK:
            if _TRADING_BOT:
                logging.warning("🔄 Force restart requested via API")
                _TRADING_BOT = None
                
        start_trading_loop()
        return jsonify({"ok": True, "message": "Trading bot restarted"})
        
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ================== CLEANUP FOR GUNICORN ==================
def cleanup_on_exit():
    """Очистка при завершении работы"""
    global _TRADING_BOT
    
    logging.info("🛑 Shutting down trading bot...")
    
    try:
        with _TRADING_BOT_LOCK:
            if _TRADING_BOT:
                # Здесь можно добавить логику корректного завершения
                _TRADING_BOT = None
                logging.info("✅ Trading bot shut down")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")
    
    # Удаляем lock файлы
    for lock_file in [LOCK_FILE, WEBHOOK_LOCK_FILE]:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except:
            pass

# Регистрируем cleanup для Gunicorn
atexit.register(cleanup_on_exit)

# ================== GUNICORN STARTUP ==================
# ✅ GUNICORN: Инициализация при импорте модуля
_bootstrap_once()

# ✅ GUNICORN: Экспортируем app для Gunicorn
# В Procfile: gunicorn --bind 0.0.0.0:$PORT app:app
if __name__ == "__main__":
    # Это для локального тестирования
    logging.info("🔧 Running in development mode")
    app.run(host="0.0.0.0", port=CFG.PORT, debug=False, threaded=True)