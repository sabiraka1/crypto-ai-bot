from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.migrations.runner import apply_all
from crypto_ai_bot.core.storage.sqlite_maint import apply_connection_pragmas

from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository


@dataclass
class Container:
    settings: Settings
    con: sqlite3.Connection
    broker: Any
    bus: AsyncEventBus
    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    exits_repo: SqliteProtectiveExitsRepository
    idempotency_repo: IdempotencyRepository
    audit_repo: SqliteAuditRepository


def build_container() -> Container:
    cfg = Settings.build()

    # DB
    con = connect(getattr(cfg, "DB_PATH", ":memory:"))
    apply_connection_pragmas(con, cfg)   # безопасные PRAGMA
    apply_all(con)

    # repos
    trades = SqliteTradeRepository(con)
    positions = SqlitePositionRepository(con)
    exits = SqliteProtectiveExitsRepository(con)
    idem = IdempotencyRepository(con)
    audit = SqliteAuditRepository(con)

    # bus (совместимо с текущим AsyncEventBus)
    bus = AsyncEventBus(
        max_queue=int(getattr(cfg, "BUS_MAX_QUEUE", 2000)),
        concurrency=int(getattr(cfg, "BUS_WORKERS", 4)),
    )
    # ВАЖНО: не запускаем здесь; запуск/остановка в FastAPI lifespan (app/server.py)

    # broker
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
