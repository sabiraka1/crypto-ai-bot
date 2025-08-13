# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import logging
from fastapi import FastAPI

from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.core.events import EventBus
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.trading.position_manager import PositionManager
from crypto_ai_bot.trading.risk_manager import RiskManager
from crypto_ai_bot.trading.bot import TradingBot, Deps

from crypto_ai_bot.app.health import router as health_router, build_status_router
from crypto_ai_bot.core.metrics import router as metrics_router
from crypto_ai_bot.telegram.bot import router as telegram_router

logger = logging.getLogger(__name__)


def build_deps() -> Deps:
    cfg = Settings.load()
    events = EventBus()

    # ExchangeClient может быть с аргументом cfg или без аргументов — поддержим оба варианта.
    try:
        exchange = ExchangeClient(cfg)  # новый вариант
    except TypeError:
        exchange = ExchangeClient()     # старый вариант без аргументов
    except Exception as e:
        logger.warning(f"ExchangeClient init with cfg failed: {e}; falling back to no-arg")
        exchange = ExchangeClient()

    state = StateManager(cfg)
    risk = RiskManager(cfg)
    positions = PositionManager(exchange=exchange, state=state, settings=cfg, events=events)
    return Deps(settings=cfg, exchange=exchange, state=state, risk=risk, positions=positions, events=events)


def create_app() -> FastAPI:
    logging.getLogger().setLevel(logging.INFO)
    deps = build_deps()
    bot = TradingBot(deps)

    app = FastAPI(title="crypto-ai-bot", version="1.0")

    # Routers
    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(build_status_router(bot, deps), tags=["status"])
    app.include_router(metrics_router, tags=["metrics"])
    app.include_router(telegram_router, prefix="/telegram", tags=["telegram"])

    @app.on_event("startup")
    async def _startup():
        logger.info("API startup: launching bot…")
        bot.start()

    @app.on_event("shutdown")
    async def _shutdown():
        logger.info("API shutdown: stopping bot…")
        bot.stop()

    return app


app = create_app()
