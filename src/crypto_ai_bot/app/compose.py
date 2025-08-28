from __future__ import annotations

import os
import sqlite3  # ← добавлен импорт
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.brokers.paper import PaperBroker
from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CcxtBroker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.infrastructure.safety.instance_lock import InstanceLock
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec

_log = get_logger("compose")


@dataclass
class Container:
    settings: Settings
    storage: Storage
    broker: IBroker
    bus: AsyncEventBus
    health: HealthChecker
    risk: RiskManager
    exits: ProtectiveExits
    orchestrator: Orchestrator
    lock: Optional[InstanceLock] = None


def _create_storage_for_mode(settings: Settings) -> Storage:
    db_path = settings.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn, now_ms=now_ms())
    storage = Storage.from_connection(conn)
    _log.info("storage_created", extra={"mode": settings.MODE, "db_path": db_path})
    return storage


def _create_broker_for_mode(settings: Settings) -> IBroker:
    mode = (settings.MODE or "").lower()
    if mode == "paper":
        balances = {"USDT": dec("10000")}
        return PaperBroker(symbol=settings.SYMBOL, balances=balances)
    if mode == "live":
        # Fail-fast: ключи обязательны в live
        if not settings.API_KEY or not settings.API_SECRET:
            raise ValueError("API creds required in live mode")
        return CcxtBroker(
            exchange_id=settings.EXCHANGE,
            api_key=settings.API_KEY,
            api_secret=settings.API_SECRET,
            enable_rate_limit=True,
            sandbox=bool(settings.SANDBOX),
            dry_run=False,
        )
    raise ValueError(f"Unknown MODE={settings.MODE}")


def build_container() -> Container:
    settings = Settings.load()
    storage = _create_storage_for_mode(settings)
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=250, backoff_factor=2.0)
    bus.attach_logger_dlq()  # проще отлавливать сбои подписчиков

    broker = _create_broker_for_mode(settings)

    risk = RiskManager(
        config=RiskConfig(
            cooldown_sec=settings.RISK_COOLDOWN_SEC,
            max_spread_pct=settings.RISK_MAX_SPREAD_PCT,
            max_position_base=settings.RISK_MAX_POSITION_BASE,
            max_orders_per_hour=settings.RISK_MAX_ORDERS_PER_HOUR,
            daily_loss_limit_quote=settings.RISK_DAILY_LOSS_LIMIT_QUOTE,
            max_fee_pct=settings.RISK_MAX_FEE_PCT,
            max_slippage_pct=settings.RISK_MAX_SLIPPAGE_PCT,
        ),
    )

    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    health = HealthChecker(storage=storage, broker=broker, bus=bus)

    lock: Optional[InstanceLock] = None
    if settings.MODE.lower() == "live":
        try:
            lock_owner = settings.POD_NAME or settings.HOSTNAME or "local"
            lock = InstanceLock(storage.conn, app="trader", owner=lock_owner)
            lock.acquire(ttl_sec=300)
        except Exception as exc:
            _log.error("lock_init_failed", extra={"error": str(exc)})

    orchestrator = Orchestrator(
        symbol=settings.SYMBOL,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        settings=settings,
    )

    return Container(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        health=health,
        risk=risk,
        exits=exits,
        orchestrator=orchestrator,
        lock=lock,
    )