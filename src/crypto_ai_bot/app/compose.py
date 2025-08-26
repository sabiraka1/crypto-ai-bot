from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..core.settings import Settings
from ..core.events.bus import AsyncEventBus
from ..core.storage.migrations.runner import run_migrations
from ..core.storage.facade import Storage
from ..core.monitoring.health_checker import HealthChecker
from ..core.risk.manager import RiskManager, RiskConfig
from ..core.risk.protective_exits import ProtectiveExits
from ..core.brokers.base import IBroker
from ..core.brokers.paper import PaperBroker
from ..core.brokers.ccxt_adapter import CcxtBroker
from ..core.orchestrator import Orchestrator
from ..core.safety.instance_lock import InstanceLock
from ..utils.time import now_ms
from ..utils.logging import get_logger

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
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 🔒 миграции + бэкап (ретеншн управляется BACKUP_RETENTION_DAYS, по умолчанию 30)
    retention = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=True, backup_retention_days=retention)

    storage = Storage.from_connection(conn)
    _log.info("storage_created", extra={"mode": settings.MODE, "db_path": db_path})
    return storage


def _create_broker_for_mode(settings: Settings) -> IBroker:
    mode = settings.MODE.lower()
    if mode == "paper":
        balances = {"USDT": Decimal("10000")}
        return PaperBroker(symbol=settings.SYMBOL, balances=balances)
    elif mode == "live":
        return CcxtBroker(
            exchange_id=settings.EXCHANGE,
            api_key=settings.API_KEY,
            api_secret=settings.API_SECRET,
            enable_rate_limit=True,
            sandbox=bool(settings.SANDBOX),
            dry_run=False,
        )
    else:
        raise ValueError(f"Unknown MODE={settings.MODE}")


def build_container() -> Container:
    settings = Settings.load()
    storage = _create_storage_for_mode(settings)
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=250, backoff_factor=2.0)
    broker = _create_broker_for_mode(settings)
    risk = RiskManager(
        storage=storage,
        config=RiskConfig(
            cooldown_sec=settings.RISK_COOLDOWN_SEC,
            max_spread_pct=settings.RISK_MAX_SPREAD_PCT,
            max_position_base=settings.RISK_MAX_POSITION_BASE,
            max_orders_per_hour=settings.RISK_MAX_ORDERS_PER_HOUR,
            daily_loss_limit_quote=settings.RISK_DAILY_LOSS_LIMIT_QUOTE,
        ),
    )
    exits = ProtectiveExits(storage=storage, bus=bus)
    health = HealthChecker(storage=storage, broker=broker, bus=bus)

    lock = None
    if settings.MODE == "live":
        try:
            lock_owner = os.getenv("POD_NAME", os.getenv("HOSTNAME", "local"))
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
