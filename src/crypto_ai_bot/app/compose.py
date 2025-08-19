# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.events.bus import AsyncEventBus

from crypto_ai_bot.core.storage.sqlite_adapter import (
    connect,
    apply_connection_pragmas,
)
from crypto_ai_bot.core.storage.migrations.runner import apply_all

from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import (
    SqliteProtectiveExitsRepository,
)
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository


@dataclass
class Container:
    settings: Settings
    con: sqlite3.Connection
    broker: object
    bus: AsyncEventBus
    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    exits_repo: SqliteProtectiveExitsRepository
    idempotency_repo: IdempotencyRepository
    audit_repo: SqliteAuditRepository


def build_container(settings: Optional[Settings] = None) -> Container:
    """
    Собирает DI-контейнер. Ничего не «стартует» (bus/orchestrator поднимаются в server.lifespan).
    """
    cfg = settings or Settings.build()

    # --- DB connect + PRAGMA + миграции ---
    con = connect(cfg.DB_PATH)
    apply_connection_pragmas(con)
    apply_all(con)

    # --- Event Bus (без старта тут) ---
    max_queue = int(getattr(cfg, "BUS_MAX_QUEUE", 2000))
    workers = int(getattr(cfg, "BUS_WORKERS", 4))
    # допускаем расширенную сигнатуру, если она у вас в bus уже есть:
    bus = AsyncEventBus(max_queue=max_queue, concurrency=workers)

    # --- Repos ---
    trades = SqliteTradeRepository(con)
    positions = SqlitePositionRepository(con)
    exits = SqliteProtectiveExitsRepository(con)
    idem = IdempotencyRepository(con)
    audit = SqliteAuditRepository(con)

    # --- Broker (с лимитами/ретраями/CB внутри реализации) ---
    broker = create_broker(cfg, bus=bus)

    return Container(
        settings=cfg,
        con=con,
        broker=broker,
        bus=bus,
        trades_repo=trades,
        positions_repo=positions,
        exits_repo=exits,
        idempotency_repo=idem,
        audit_repo=audit,
    )
