# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import sqlite3

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.orchestrator import Orchestrator

# БД (консолидированный адаптер)
from crypto_ai_bot.core.storage.sqlite_adapter import connect, apply_connection_pragmas

# Репозитории
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository

# Брокер
from crypto_ai_bot.core.brokers.base import create_broker


@dataclass
class Container:
    settings: Settings
    sqlite: sqlite3.Connection
    broker: Any
    bus: AsyncEventBus
    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    exits_repo: SqliteProtectiveExitsRepository
    idempotency_repo: IdempotencyRepository
    audit_repo: SqliteAuditRepository
    orchestrator: Orchestrator


def build_container(settings: Settings) -> Container:
    # DB
    con = connect(getattr(settings, "DB_PATH", ":memory:"))
    apply_connection_pragmas(con, settings)

    # Broker
    broker = create_broker(settings)

    # Event Bus
    bus = AsyncEventBus(
        max_queue=int(getattr(settings, "EVENT_BUS_MAX_SIZE", 4096)),
        concurrency=int(getattr(settings, "EVENT_BUS_CONCURRENCY", 4)),
    )

    # Repos
    trades_repo = SqliteTradeRepository(con)
    positions_repo = SqlitePositionRepository(con)
    exits_repo = SqliteProtectiveExitsRepository(con)
    idempotency_repo = IdempotencyRepository(con)
    audit_repo = SqliteAuditRepository(con)

    # Orchestrator (единая точка жизненного цикла)
    orchestrator = Orchestrator(
        settings=settings,
        broker=broker,
        bus=bus,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        idempotency_repo=idempotency_repo,
        audit_repo=audit_repo,
        sqlite=con,
    )

    return Container(
        settings=settings,
        sqlite=con,
        broker=broker,
        bus=bus,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        idempotency_repo=idempotency_repo,
        audit_repo=audit_repo,
        orchestrator=orchestrator,
    )
