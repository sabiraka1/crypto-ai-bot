# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

import os
from dataclasses import dataclass

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.storage.sqlite_adapter import connect, apply_connection_pragmas
from crypto_ai_bot.core.storage.migrations.runner import apply_all

# Репозитории
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository


@dataclass
class Container:
    settings: Settings
    con: "sqlite3.Connection"
    bus: AsyncEventBus
    broker: object

    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    exits_repo: SqliteProtectiveExitsRepository
    idempotency_repo: IdempotencyRepository
    audit_repo: SqliteAuditRepository


def build_container() -> Container:
    """
    Сборка DI-контейнера приложения.
    ВАЖНО:
      - Settings загружаем через Settings.load() (никаких .build()).
      - Директорию БД создаём заранее.
      - PRAGMA применяем из sqlite_adapter (никаких sqlite_maint).
      - bus.start() тут НЕ вызываем: запуск шины делает сервер (lifespan/on_startup).
    """
    # 1) Настройки
    cfg = Settings.load()

    # 2) Директория БД (если путь файловый)
    db_path = cfg.DB_PATH
    db_dir = os.path.dirname(db_path) if db_path else ""
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # 3) Подключение к БД + PRAGMA + миграции
    con = connect(db_path)
    apply_connection_pragmas(con)
    apply_all(con)

    # 4) Репозитории
    trades = SqliteTradeRepository(con)
    positions = SqlitePositionRepository(con)
    exits = SqliteProtectiveExitsRepository(con)
    idem = IdempotencyRepository(con)
    audit = SqliteAuditRepository(con)

    # 5) Event Bus (параметры берём из Settings, с дефолтами)
    max_queue = int(getattr(cfg, "BUS_MAX_QUEUE", 2048))
    concurrency = int(getattr(cfg, "BUS_CONCURRENCY", 4))
    bus = AsyncEventBus(max_queue=max_queue, concurrency=concurrency)

    # 6) Брокер
    broker = create_broker(cfg, bus=bus)

    return Container(
        settings=cfg,
        con=con,
        bus=bus,
        broker=broker,
        trades_repo=trades,
        positions_repo=positions,
        exits_repo=exits,
        idempotency_repo=idem,
        audit_repo=audit,
    )
