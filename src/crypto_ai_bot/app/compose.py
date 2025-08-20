# src/crypto_ai_bot/app/compose.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.brokers.ccxt_exchange import CCXTExchange
from crypto_ai_bot.utils.rate_limit import TokenBucket, MultiLimiter

# SQLite adapter + репозитории (имена модулей соответствуют текущей структуре)
from crypto_ai_bot.core.storage.sqlite_adapter import connect_sqlite

from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository


@dataclass
class Container:
    settings: Settings
    bus: AsyncEventBus
    broker: CCXTExchange

    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    exits_repo: SqliteProtectiveExitsRepository
    idempotency_repo: SqliteIdempotencyRepository
    audit_repo: SqliteAuditRepository


def build_container(settings: Optional[Settings] = None) -> Container:
    """
    Собирает все зависимости. НИЧЕГО не запускает (bus.start/stop — в server.lifespan).
    """
    s = settings or Settings.load()

    # ----- Storage -----
    conn = connect_sqlite(db_path=s.DB_PATH)  # применяет PRAGMA/WAL внутри

    trades_repo = SqliteTradeRepository(conn)
    positions_repo = SqlitePositionRepository(conn)
    exits_repo = SqliteProtectiveExitsRepository(conn)
    idempotency_repo = SqliteIdempotencyRepository(conn)
    audit_repo = SqliteAuditRepository(conn)

    # ----- Event Bus (конфиг через Settings, с дефолтами) -----
    bus = AsyncEventBus(
        max_queue=getattr(s, "BUS_MAX_QUEUE", 1000),
        concurrency=getattr(s, "BUS_CONCURRENCY", 4),
    )

    # ----- Rate limiting для брокера -----
    limiter = MultiLimiter({
        "orders":      TokenBucket(capacity=getattr(s, "RL_ORDERS_CAP", 100),
                                   refill_per_sec=getattr(s, "RL_ORDERS_RPS", 10)),
        "market_data": TokenBucket(capacity=getattr(s, "RL_MD_CAP", 600),
                                   refill_per_sec=getattr(s, "RL_MD_RPS", 60)),
        "account":     TokenBucket(capacity=getattr(s, "RL_ACC_CAP", 300),
                                   refill_per_sec=getattr(s, "RL_ACC_RPS", 30)),
    })

    # ----- Broker -----
    broker = CCXTExchange(settings=s, limiter=limiter)

    return Container(
        settings=s,
        bus=bus,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        idempotency_repo=idempotency_repo,
        audit_repo=audit_repo,
    )
