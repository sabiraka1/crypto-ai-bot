# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

import os
from dataclasses import dataclass

from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.orchestrator import Orchestrator
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.exits import SqliteExitRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.sqlite_adapter import connect, apply_connection_pragmas
from crypto_ai_bot.core.brokers.ccxt_exchange import CCXTExchange
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Container:
    settings: Settings
    db: object
    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    exits_repo: SqliteExitRepository
    idempotency_repo: SqliteIdempotencyRepository
    audit_repo: SqliteAuditRepository
    broker: CCXTExchange
    bus: AsyncEventBus
    orchestrator: Orchestrator


def build_container() -> Container:
    # Settings
    settings = Settings.load()

    # Ensure DB dir exists
    db_path = settings.DB_PATH
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # DB
    db = connect(db_path)
    apply_connection_pragmas(db)

    # Repositories
    trades_repo = SqliteTradeRepository(db)
    positions_repo = SqlitePositionRepository(db)
    exits_repo = SqliteExitRepository(db)
    idempotency_repo = SqliteIdempotencyRepository(db)
    audit_repo = SqliteAuditRepository(db)

    # Event bus (do NOT start here; server lifespan will)
    bus = AsyncEventBus(max_queue=settings.BUS_MAX_QUEUE, concurrency=settings.BUS_CONCURRENCY)

    # Broker
    broker = CCXTExchange(settings=settings)

    # Orchestrator
    orchestrator = Orchestrator(
        settings=settings,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        idempotency_repo=idempotency_repo,
        audit_repo=audit_repo,
        bus=bus,
    )

    logger.info("Container built: mode=%s db=%s exchange=%s", settings.MODE, settings.DB_PATH, settings.EXCHANGE)
    return Container(
        settings=settings,
        db=db,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        idempotency_repo=idempotency_repo,
        audit_repo=audit_repo,
        broker=broker,
        bus=bus,
        orchestrator=orchestrator,
    )
