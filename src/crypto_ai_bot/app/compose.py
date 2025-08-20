# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import sqlite3

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.events.bus import AsyncEventBus

# Хранилище (консолидированный адаптер с PRAGMA/backup и т.д.)
from crypto_ai_bot.core.storage.sqlite_adapter import connect, apply_connection_pragmas

# Репозитории (пути и классы — как в текущем репозитории)
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository

# Фабрика брокера (обёртка над CCXT в соответствии с настройками)
from crypto_ai_bot.core.brokers.base import create_broker


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
    # ВАЖНО: используем Settings.load(), а не build()
    cfg = Settings.load()

    # DB
    con = connect(getattr(cfg, "DB_PATH", ":memory:"))
    # Применяем PRAGMA согласно настройкам (safe defaults внутри адаптера)
    apply_connection_pragmas(con, cfg)

    # Broker
    broker = create_broker(cfg)

    # Event Bus (актуальная сигнатура)
    bus = AsyncEventBus(
        max_queue=int(getattr(cfg, "EVENT_BUS_MAX_SIZE", 4096)),
        concurrency=int(getattr(cfg, "EVENT_BUS_CONCURRENCY", 4)),
    )

    # Repositories
    trades_repo = SqliteTradeRepository(con)
    positions_repo = SqlitePositionRepository(con)
    exits_repo = SqliteProtectiveExitsRepository(con)
    idempotency_repo = IdempotencyRepository(con)
    audit_repo = SqliteAuditRepository(con)

    return Container(
        settings=cfg,
        con=con,
        broker=broker,
        bus=bus,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        idempotency_repo=idempotency_repo,
        audit_repo=audit_repo,
    )
