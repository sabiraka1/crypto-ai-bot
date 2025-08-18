from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.storage.sqlite_adapter import connect as sqlite_connect
from crypto_ai_bot.core.storage.migrations.runner import apply_all as apply_migrations

from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository

from crypto_ai_bot.app.bus_wiring import build_event_bus
from crypto_ai_bot.core.brokers.ccxt_impl import CCXTExchange  # CCXT-адаптер (Gate.io поддерживается)


@dataclass
class Container:
    settings: Settings
    con: Any
    trades_repo: SqliteTradeRepository
    positions_repo: SqlitePositionRepository
    audit_repo: SqliteAuditRepository
    idempotency_repo: SqliteIdempotencyRepository
    exits_repo: SqliteProtectiveExitsRepository
    bus: Any
    broker: CCXTExchange


def build_container() -> Container:
    """
    Composition Root:
    - строим настройки
    - открываем БД и применяем миграции
    - собираем репозитории
    - поднимаем шину событий
    - создаём брокер
    """
    cfg = Settings.build()

    # БД
    con = sqlite_connect(cfg.DB_PATH)
    apply_migrations(con)

    # Репозитории
    trades = SqliteTradeRepository(con)
    positions = SqlitePositionRepository(con)
    audit = SqliteAuditRepository(con)
    idem = SqliteIdempotencyRepository(con)
    exits = SqliteProtectiveExitsRepository(con)

    # Шина событий
    bus = build_event_bus(cfg)

    # Брокер (через CCXT). Символы в формате CCXT: BASE/QUOTE, напр. 'BTC/USDT'
    broker = CCXTExchange(settings=cfg, bus=bus, exchange_name=cfg.EXCHANGE)

    return Container(
        settings=cfg,
        con=con,
        trades_repo=trades,
        positions_repo=positions,
        audit_repo=audit,
        idempotency_repo=idem,
        exits_repo=exits,
        bus=bus,
        broker=broker,
    )
