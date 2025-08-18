# src/crypto_ai_bot/app/compose.py
from dataclasses import dataclass
from typing import Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.storage.sqlite_adapter import connect as sqlite_connect
from crypto_ai_bot.core.storage.migrations.runner import apply_all as apply_migrations
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.app.bus_wiring import build_event_bus
from crypto_ai_bot.core.brokers.ccxt_impl import CCXTExchange  # через CCXT на gateio

@dataclass
class Container:
    settings: Settings
    con: any
    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    audit_repo: SqliteAuditRepository
    idempotency_repo: SqliteIdempotencyRepository
    bus: any
    broker: CCXTExchange

def build_container() -> Container:
    cfg = Settings.build()  # централизованная конфигурация
    con = sqlite_connect(cfg.DB_PATH)  # WAL, pragmas внутри адаптера
    apply_migrations(con)              # авто-миграции при старте

    trades = SqliteTradeRepository(con)
    positions = SqlitePositionRepository(con)
    audit = SqliteAuditRepository(con)
    idem = SqliteIdempotencyRepository(con)

    bus = build_event_bus(cfg)         # единая шина событий (см. PR-2)
    broker = CCXTExchange(settings=cfg, bus=bus, exchange_name=cfg.EXCHANGE)

    return Container(
        settings=cfg, con=con,
        trades_repo=trades, positions_repo=positions,
        audit_repo=audit, idempotency_repo=idem,
        bus=bus, broker=broker
    )
