# main.py — тонкий лаунчер воркера (бота)

import os
import sys
import time
import signal
import logging
from pathlib import Path
from typing import Type

# --- подготовка путей и логов ------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
DATA_DIR = REPO_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)  # гарантируем, что каталог логов существует

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# --- Импорты из вашего пакета ------------------------------------------------
from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.core.events import EventBus
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.trading.position_manager import PositionManager
from crypto_ai_bot.trading.risk_manager import RiskManager

# Поддержим оба варианта названия датакласса зависимостей (Deps или TradingDeps)
try:
    from crypto_ai_bot.trading.bot import TradingBot, Deps as _Deps  # рекомендованный нейминг
except Exception:
    from crypto_ai_bot.trading.bot import TradingBot, TradingDeps as _Deps  # если у тебя другой

Deps: Type[_Deps] = _Deps  # type: ignore[assignment]


def build_deps() -> Deps:
    """Создаём зависимости бота из конфигурации."""
    logger.info("🔧 Building bot dependencies...")

    # 1) Конфиг
    cfg = Settings.load() if hasattr(Settings, "load") else Settings()  # type: ignore[operator]
    # NEW: выставим уровень логов из конфига и выведем сводку/предупреждения
    try:
        logging.getLogger().setLevel(getattr(logging, str(cfg.LOG_LEVEL).upper(), logging.INFO))
    except Exception:
        pass
    logger.info(cfg.summary())
    issues = cfg.validate()
    for err in issues:
        logger.warning(f"⚠️ Config issue: {err}")
    logger.info("✅ Configuration loaded")

    # 2) Общие сервисы
    events = EventBus()
    exchange = ExchangeClient(cfg)
    state = StateManager(cfg)
    risk = RiskManager(cfg)

    # 3) PositionManager ожидает (exchange, state, settings, events)
    positions = PositionManager(
        exchange=exchange,
        state=state,
        settings=cfg,
        events=events,
    )

    deps = Deps(
        settings=cfg,
        exchange=exchange,
        state=state,
        risk=risk,
        positions=positions,
        events=events,
    )

    logger.info("✅ All dependencies initialized")
    return deps


def run() -> None:
    """Запуск бота и аккуратная остановка по Ctrl+C / SIGTERM."""
    logger.info("🚀 Trading bot starting...")

    deps = build_deps()
    bot = TradingBot(deps)

    def graceful_stop(*_args):
        logger.info("🛑 Received shutdown signal, stopping bot gracefully...")
        try:
            bot.stop()
            logger.info("✅ Bot stopped successfully")
        except Exception as e:
            logger.error(f"❌ Error during bot shutdown: {e}")
        finally:
            sys.exit(0)

    # Регистрируем обработчики сигналов (на Windows SIGTERM может быть недоступен — это ок)
    try:
        signal.signal(signal.SIGTERM, graceful_stop)
    except Exception as e:
        logger.debug(f"SIGTERM handler not set: {e}")
    try:
        signal.signal(signal.SIGINT, graceful_stop)
    except Exception as e:
        logger.debug(f"SIGINT handler not set: {e}")

    logger.info("🚀 Trading bot started successfully!")
    bot.start()

    # Кроссплатформенное «ожидание жизни» процесса
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        graceful_stop()


if __name__ == "__main__":
    run()
