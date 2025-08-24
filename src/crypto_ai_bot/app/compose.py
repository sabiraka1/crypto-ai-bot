from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from ..core.settings import Settings, ValidationError
from ..core.storage.migrations.runner import run_migrations
from ..core.storage.facade import Storage
from ..core.events.bus import AsyncEventBus
from ..core.monitoring.health_checker import HealthChecker
from ..core.risk.manager import RiskManager, RiskConfig
from ..core.risk.protective_exits import ProtectiveExits
from ..core.orchestrator import Orchestrator
from ..core.safety.instance_lock import InstanceLock  # ← добавлено
from ..utils.time import now_ms
from ..utils.logging import get_logger

# брокеры
try:
    from ..core.brokers.paper import PaperBroker
except Exception:  # pragma: no cover
    PaperBroker = None  # type: ignore

try:
    from ..core.brokers.ccxt_exchange import CcxtBroker
except Exception:  # pragma: no cover
    CcxtBroker = None  # type: ignore


_log = get_logger("compose")


@dataclass
class Container:
    settings: Settings
    storage: Storage
    broker: "object"
    bus: AsyncEventBus
    health: HealthChecker
    risk: RiskManager
    exits: ProtectiveExits
    orchestrator: Orchestrator
    instance_lock: InstanceLock  # ← добавлено


def _create_storage_for_mode(settings: Settings) -> Storage:
    if settings.DB_PATH == ":memory:":
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
        conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)

    conn.row_factory = sqlite3.Row
    run_migrations(conn, now_ms=now_ms())
    _log.info("storage_created", extra={"mode": settings.MODE, "db_path": settings.DB_PATH})
    return Storage(conn)


def _create_broker_for_mode(settings: Settings, storage: Storage):
    if settings.MODE == "paper":
        if PaperBroker is None:
            raise RuntimeError("PaperBroker not available")
        balances = {"USDT": Decimal("10000")}
        _log.info("creating_paper_broker", extra={"mode": settings.MODE, "balances": balances})
        return PaperBroker(balances=balances)

    if CcxtBroker is None:
        raise RuntimeError("CcxtBroker not available")
    if not settings.API_KEY or not settings.API_SECRET:
        raise ValidationError("MODE=live requires API_KEY and API_SECRET")

    _log.info("creating_ccxt_broker", extra={"exchange": settings.EXCHANGE})
    return CcxtBroker(
        exchange_id=settings.EXCHANGE,
        api_key=settings.API_KEY,
        api_secret=settings.API_SECRET,
        enable_rate_limit=True,
    )


def build_container() -> Container:
    settings = Settings.load()

    _log.info("building_container", extra={
        "mode": settings.MODE,
        "exchange": settings.EXCHANGE,
        "symbol": settings.SYMBOL,
    })

    storage = _create_storage_for_mode(settings)
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=250, backoff_factor=2.0)
    broker = _create_broker_for_mode(settings, storage)

    risk_config = RiskConfig(
        cooldown_sec=settings.RISK_COOLDOWN_SEC,
        max_spread_pct=settings.RISK_MAX_SPREAD_PCT,
        max_position_base=settings.RISK_MAX_POSITION_BASE,
        max_orders_per_hour=settings.RISK_MAX_ORDERS_PER_HOUR,
        daily_loss_limit_quote=settings.RISK_DAILY_LOSS_LIMIT_QUOTE,
    )
    risk = RiskManager(storage=storage, config=risk_config)
    exits = ProtectiveExits(broker=broker, storage=storage, bus=bus)
    health = HealthChecker(storage=storage, broker=broker, bus=bus)
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
    instance_lock = InstanceLock(storage=storage)  # ← добавлено

    _log.info("container_built", extra={
        "mode": settings.MODE,
        "components": ["settings", "storage", "broker", "bus", "health", "risk", "exits", "orchestrator", "lock"],
    })

    return Container(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        health=health,
        risk=risk,
        exits=exits,
        orchestrator=orchestrator,
        instance_lock=instance_lock,
    )
