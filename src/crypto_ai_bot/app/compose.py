# src/crypto_ai_bot/app/compose.py
"""
DI-композиция: собираем settings, SQLite, репозитории, брокер, event-bus, orchestrator.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.ccxt_exchange import CCXTExchange
from crypto_ai_bot.core.orchestrator import Orchestrator
from crypto_ai_bot.core.events.bus import AsyncEventBus  # ваш bus
from crypto_ai_bot.core.storage.repositories.kv import SqliteKVRepository

# существующие репозитории (импортируй те, что у тебя в проекте)
from crypto_ai_bot.core.storage.sqlite_adapter import connect as sqlite_connect  # ваш единый адаптер
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradesRepository  # предполагается
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionsRepository  # предполагается
from crypto_ai_bot.core.storage.repositories.exits import SqliteProtectiveExitsRepository  # предполагается
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository  # предполагается
from crypto_ai_bot.utils.logging import get_logger


@dataclass
class Container:
    settings: Any
    db: sqlite3.Connection
    repositories: Any
    broker: Any
    event_bus: Any
    orchestrator: Orchestrator
    logger: Any
    # опционально: telegram_handler и т.п.


class _Repos:
    def __init__(self, conn: sqlite3.Connection):
        # инициализируй ТОЛЬКО те репозитории, которые реально есть в проекте
        self.trades_repo = SqliteTradesRepository(conn)
        self.positions_repo = SqlitePositionsRepository(conn)
        self.exits_repo = SqliteProtectiveExitsRepository(conn)
        self.idempotency_repo = SqliteIdempotencyRepository(conn)
        self.kv_repo = SqliteKVRepository(conn)
        # при наличии — self.audit_repo, self.market_meta_repo и т.п.


def build_container() -> Container:
    log = get_logger("compose")
    settings = Settings.load()  # важно: load (а не build)
    db_path = getattr(settings, "DB_PATH", "/data/bot.sqlite")

    conn = sqlite_connect(db_path)  # ваш адаптер уже включает PRAGMA/WAL и retry
    repos = _Repos(conn)

    broker = CCXTExchange(settings=settings, logger=log)
    bus = AsyncEventBus(
        # поддерживаем простую сигнатуру; если у вас иная — подставьте свои параметры
        max_queue=int(getattr(settings, "BUS_MAX_QUEUE", 1000)),
        concurrency=int(getattr(settings, "BUS_CONCURRENCY", 4)),
        logger=log,
    )

    orch = Orchestrator(
        settings=settings,
        broker=broker,
        repositories=repos,
        event_bus=bus,
        logger=log,
        # интервалы можно оставить default — читаются из settings
    )

    return Container(
        settings=settings,
        db=conn,
        repositories=repos,
        broker=broker,
        event_bus=bus,
        orchestrator=orch,
        logger=log,
    )
