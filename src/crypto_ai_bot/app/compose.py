from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.storage.sqlite_adapter import connect, apply_connection_pragmas
from crypto_ai_bot.core.storage.migrations.runner import apply_all

from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository


@dataclass
class Container:
    settings: Settings
    con: Any
    broker: Any
    bus: AsyncEventBus
    trades_repo: Any
    positions_repo: Any
    exits_repo: Any
    idempotency_repo: Any
    audit_repo: Any


def _build_bus(cfg: Settings) -> AsyncEventBus:
    """
    Создаёт AsyncEventBus, совместимый с обеими версиями конструктора:
    - новый: (max_queue, dlq_limit, workers, backpressure, enqueue_timeout_sec)
    - старый: (max_queue, concurrency)
    """
    max_queue = int(getattr(cfg, "BUS_MAX_QUEUE", 2000))
    workers = int(getattr(cfg, "BUS_WORKERS", 4))
    try:
        return AsyncEventBus(
            max_queue=max_queue,
            dlq_limit=int(getattr(cfg, "BUS_DLQ_LIMIT", 500)),
            workers=workers,
            backpressure=str(getattr(cfg, "BUS_BACKPRESSURE", "drop_new")),
            enqueue_timeout_sec=float(getattr(cfg, "BUS_ENQ_TIMEOUT_SEC", 0.5)),
        )
    except TypeError:
        # Совместимость со старой сигнатурой
        return AsyncEventBus(max_queue=max_queue, concurrency=workers)


def build_container() -> Container:
    """
    Конструирует DI-контейнер без побочных эффектов запуска.
    НИЧЕГО не стартуем здесь: ни bus, ни orchestrator.
    """
    cfg = Settings.build()  # Используем build() для загрузки из ENV

    # Ensure database directory exists
    import os
    db_path = getattr(cfg, "DB_PATH", "bot.sqlite")
    db_dir = os.path.dirname(db_path)
    
    if db_dir and db_dir != '.':
        try:
            os.makedirs(db_dir, exist_ok=True)
            print(f"Database directory ensured: {db_dir}")
        except Exception as e:
            print(f"Warning: Could not create directory {db_dir}: {e}")

    # БД
    con = connect(db_path)
    apply_connection_pragmas(con)
    apply_all(con)

    # repos
    trades = SqliteTradeRepository(con)
    positions = SqlitePositionRepository(con)
    exits = SqliteProtectiveExitsRepository(con)
    idem = SqliteIdempotencyRepository(con)
    audit = SqliteAuditRepository(con)

    # bus
    bus = _build_bus(cfg)

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