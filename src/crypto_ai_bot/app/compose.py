# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

import os
from dataclasses import dataclass

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.brokers.ccxt_exchange import create_broker  # фабрика CCXT/Backtest
from crypto_ai_bot.core.orchestrator import Orchestrator
from crypto_ai_bot.core.storage.sqlite_adapter import connect  # единая точка подключения SQLite

# Репозитории (ожидаемые имена классов в проекте)
from crypto_ai_bot.core.storage.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.protective_exits import SqliteProtectiveExitRepository
from crypto_ai_bot.core.storage.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.core.storage.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.events_journal import SqliteEventJournalRepository


@dataclass
class Repositories:
    trades: SqliteTradeRepository
    positions: SqlitePositionRepository
    exits: SqliteProtectiveExitRepository
    idempotency: SqliteIdempotencyRepository
    audit: SqliteAuditRepository
    events: SqliteEventJournalRepository


@dataclass
class Container:
    settings: Settings
    db: object  # sqlite3.Connection
    broker: object  # ExchangeInterface
    repos: Repositories
    bus: AsyncEventBus
    orchestrator: Orchestrator
    logger: object


def _ensure_db_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def build_container() -> Container:
    logger = get_logger("compose")

    # 1) настройки только через Settings.load()
    settings = Settings.load()
    _ensure_db_dir(settings.DB_PATH)

    # 2) DB connect (единый адаптер + PRAGMA внутри)
    db = connect(settings.DB_PATH)

    # 3) Repos
    trades = SqliteTradeRepository(db)
    positions = SqlitePositionRepository(db)
    exits = SqliteProtectiveExitRepository(db)
    idempotency = SqliteIdempotencyRepository(db)
    audit = SqliteAuditRepository(db)
    events = SqliteEventJournalRepository(db)
    repos = Repositories(
        trades=trades,
        positions=positions,
        exits=exits,
        idempotency=idempotency,
        audit=audit,
        events=events,
    )

    # 4) Broker (ccxt / backtest по settings)
    broker = create_broker(settings=settings, logger=logger)

    # 5) Event Bus (параметры соответствуют вашей реализации bus.py)
    bus = AsyncEventBus(
        max_queue=int(getattr(settings, "BUS_MAX_QUEUE", 1000)),
        concurrency=int(getattr(settings, "BUS_CONCURRENCY", 4)),
    )

    # 6) Orchestrator (единый lifecycle manager)
    orchestrator = Orchestrator(
        settings=settings,
        broker=broker,
        repos=repos,
        bus=bus,
        logger=get_logger("orchestrator"),
    )

    return Container(
        settings=settings,
        db=db,
        broker=broker,
        repos=repos,
        bus=bus,
        orchestrator=orchestrator,
        logger=logger,
    )
