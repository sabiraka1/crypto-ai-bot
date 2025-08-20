# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

import os
from dataclasses import dataclass

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.orchestrator import Orchestrator
from crypto_ai_bot.core.brokers.ccxt_exchange import CCXTExchange
from crypto_ai_bot.core.storage.sqlite_adapter import connect as sqlite_connect
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

@dataclass
class Container:
    settings: Settings
    broker: CCXTExchange
    db
    repos: object  # ваш уже существующий holder (trades, positions, exits, idempotency, audit, ...)
    bus: object
    orchestrator: Orchestrator

def _ensure_db_dir(db_path: str) -> None:
    d = os.path.dirname(db_path)
    if d:
        os.makedirs(d, exist_ok=True)

def build_container() -> Container:
    # ВАЖНО: Settings.load вместо несуществующего Settings.build
    settings = Settings.load()

    # Гарантируем каталог под БД
    _ensure_db_dir(settings.DB_PATH)

    # Подключение БД (один источник правды)
    db = sqlite_connect(settings.DB_PATH)

    # Репозитории (сохраняю ваш существующий конструктор/комбайнер — поменяйте
    # на реальный, если у вас иной модуль для сборки репозиториев)
    from crypto_ai_bot.core.storage.repositories import build_repositories  # noqa
    repos = build_repositories(db)

    # Event bus (как раньше)
    from crypto_ai_bot.core.events.bus import AsyncEventBus  # noqa
    bus = AsyncEventBus(
        max_queue=getattr(settings, "EVENTBUS_MAX_QUEUE", 1024),
        concurrency=getattr(settings, "EVENTBUS_CONCURRENCY", 4),
    )

    # Брокер (ccxt) с лимитами/брейкером
    broker = CCXTExchange.from_settings(settings)

    orch = Orchestrator(
        settings=settings,
        broker=broker,
        repos=repos,
        bus=bus,
    )

    container = Container(
        settings=settings,
        broker=broker,
        db=db,
        repos=repos,
        bus=bus,
        orchestrator=orch,
    )
    return container
