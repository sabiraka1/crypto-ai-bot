# main.py вЂ” С‚РѕРЅРєРёР№ Р»Р°СѓРЅС‡РµСЂ РІРѕСЂРєРµСЂР° (Р±РѕС‚Р°)

import os
import sys
import time
import signal
import logging
from pathlib import Path
from typing import Type

# --- РїРѕРґРіРѕС‚РѕРІРєР° РїСѓС‚РµР№ Рё Р»РѕРіРѕРІ ------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
DATA_DIR = REPO_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)  # РіР°СЂР°РЅС‚РёСЂСѓРµРј, С‡С‚Рѕ РєР°С‚Р°Р»РѕРі Р»РѕРіРѕРІ СЃСѓС‰РµСЃС‚РІСѓРµС‚

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

# --- РРјРїРѕСЂС‚С‹ РёР· РІР°С€РµРіРѕ РїР°РєРµС‚Р° ------------------------------------------------
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.core.events import EventBus
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.trading.position_manager import PositionManager
from crypto_ai_bot.trading.risk_manager import RiskManager

# РџРѕРґРґРµСЂР¶РёРј РѕР±Р° РІР°СЂРёР°РЅС‚Р° РЅР°Р·РІР°РЅРёСЏ РґР°С‚Р°РєР»Р°СЃСЃР° Р·Р°РІРёСЃРёРјРѕСЃС‚РµР№ (Deps РёР»Рё TradingDeps)
try:
    from crypto_ai_bot.trading.bot import TradingBot, Deps as _Deps  # СЂРµРєРѕРјРµРЅРґРѕРІР°РЅРЅС‹Р№ РЅРµР№РјРёРЅРі
except Exception:
    from crypto_ai_bot.trading.bot import TradingBot, TradingDeps as _Deps  # РµСЃР»Рё Сѓ С‚РµР±СЏ РґСЂСѓРіРѕР№

Deps: Type[_Deps] = _Deps  # type: ignore[assignment]


def build_deps() -> Deps:
    """РЎРѕР·РґР°С‘Рј Р·Р°РІРёСЃРёРјРѕСЃС‚Рё Р±РѕС‚Р° РёР· РєРѕРЅС„РёРіСѓСЂР°С†РёРё."""
    logger.info("рџ”§ Building bot dependencies...")

    # 1) РљРѕРЅС„РёРі
    cfg = Settings.load() if hasattr(Settings, "load") else Settings()  # type: ignore[operator]
    # NEW: РІС‹СЃС‚Р°РІРёРј СѓСЂРѕРІРµРЅСЊ Р»РѕРіРѕРІ РёР· РєРѕРЅС„РёРіР° Рё РІС‹РІРµРґРµРј СЃРІРѕРґРєСѓ/РїСЂРµРґСѓРїСЂРµР¶РґРµРЅРёСЏ
    try:
        logging.getLogger().setLevel(getattr(logging, str(cfg.LOG_LEVEL).upper(), logging.INFO))
    except Exception:
        pass
    logger.info(cfg.summary())
    issues = cfg.validate()
    for err in issues:
        logger.warning(f"вљ пёЏ Config issue: {err}")
    logger.info("вњ… Configuration loaded")

    # 2) РћР±С‰РёРµ СЃРµСЂРІРёСЃС‹
    events = EventBus()
    exchange = ExchangeClient(cfg)
    state = StateManager(cfg)
    risk = RiskManager(cfg)

    # 3) PositionManager РѕР¶РёРґР°РµС‚ (exchange, state, settings, events)
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

    logger.info("вњ… All dependencies initialized")
    return deps


def run() -> None:
    """Р—Р°РїСѓСЃРє Р±РѕС‚Р° Рё Р°РєРєСѓСЂР°С‚РЅР°СЏ РѕСЃС‚Р°РЅРѕРІРєР° РїРѕ Ctrl+C / SIGTERM."""
    logger.info("рџљЂ Trading bot starting...")

    deps = build_deps()
    bot = TradingBot(deps)

    def graceful_stop(*_args):
        logger.info("рџ›‘ Received shutdown signal, stopping bot gracefully...")
        try:
            bot.stop()
            logger.info("вњ… Bot stopped successfully")
        except Exception as e:
            logger.error(f"вќЊ Error during bot shutdown: {e}")
        finally:
            sys.exit(0)

    # Р РµРіРёСЃС‚СЂРёСЂСѓРµРј РѕР±СЂР°Р±РѕС‚С‡РёРєРё СЃРёРіРЅР°Р»РѕРІ (РЅР° Windows SIGTERM РјРѕР¶РµС‚ Р±С‹С‚СЊ РЅРµРґРѕСЃС‚СѓРїРµРЅ вЂ” СЌС‚Рѕ РѕРє)
    try:
        signal.signal(signal.SIGTERM, graceful_stop)
    except Exception as e:
        logger.debug(f"SIGTERM handler not set: {e}")
    try:
        signal.signal(signal.SIGINT, graceful_stop)
    except Exception as e:
        logger.debug(f"SIGINT handler not set: {e}")

    logger.info("рџљЂ Trading bot started successfully!")
    bot.start()

    # РљСЂРѕСЃСЃРїР»Р°С‚С„РѕСЂРјРµРЅРЅРѕРµ В«РѕР¶РёРґР°РЅРёРµ Р¶РёР·РЅРёВ» РїСЂРѕС†РµСЃСЃР°
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        graceful_stop()


if __name__ == "__main__":
    run()





