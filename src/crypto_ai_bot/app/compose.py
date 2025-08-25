from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from ..core.settings import Settings
from ..core.events.bus import AsyncEventBus
from ..core.storage.migrations.runner import run_migrations
from ..core.storage.facade import Storage
from ..core.monitoring.health_checker import HealthChecker
from ..core.risk.manager import RiskManager, RiskConfig
from ..core.risk.protective_exits import ProtectiveExits
from ..core.brokers.base import IBroker
from ..core.brokers.paper_broker import PaperBroker
from ..core.brokers.ccxt_exchange import CcxtBroker
from ..core.orchestrator import Orchestrator
from ..core.safety.instance_lock import InstanceLock
from ..core.alerts import register_alerts

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
    lock: InstanceLock  # DB-lock для single instance


# --- helpers ------------------------------------------------------------------

def _create_storage_for_mode(settings: Settings) -> Storage:
    db_path = settings.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # применяем миграции
    run_migrations(conn, now_ms=now_ms())

    storage = Storage(conn)

    _log.info("storage_created", extra={
        "mode": settings.MODE,
        "db_path": db_path,
    })
    return storage


def _create_broker_for_mode(settings: Settings, storage: Storage) -> IBroker:
    mode = settings.MODE.lower()
    if mode == "paper":
        # Пожирнее тестовый баланс — удобно для e2e/PnL
        balances = {"USDT": str(Decimal("10000"))}
        _log.info("creating_paper_broker", extra={"balances": balances})
        return PaperBroker(balances=balances)
    elif mode == "live":
        return CcxtBroker(
            exchange_id=settings.EXCHANGE,
            api_key=settings.API_KEY,
            api_secret=settings.API_SECRET,
            enable_rate_limit=True,
        )
    else:
        raise ValueError(f"Unknown MODE={settings.MODE}")


# --- public -------------------------------------------------------------------

def build_container() -> Container:
    """Сборка контейнера с правильной инициализацией компонентов."""
    # 1) Settings
    settings = Settings.load()
    _log.info("building_container", extra={
        "mode": settings.MODE,
        "exchange": settings.EXCHANGE,
        "symbol": settings.SYMBOL,
    })

    # 2) Storage (DB + миграции)
    storage = _create_storage_for_mode(settings)

    # 3) DB-lock (single instance)
    lock_owner = os.getenv("POD_NAME", os.getenv("HOSTNAME", "local"))
    lock = InstanceLock(storage=storage, app="crypto-ai-bot", owner=lock_owner)
    if not lock.acquire(ttl_sec=300):
        raise RuntimeError("Instance lock not acquired: another instance is running")

    # 4) Event bus + алерты
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=250, backoff_factor=2.0)
    register_alerts(bus)  # подписчики алертов на reconcile-топики

    # 5) Broker
    broker = _create_broker_for_mode(settings, storage)

    # 6) Risk + Exits
    risk_config = RiskConfig(
        cooldown_sec=settings.RISK_COOLDOWN_SEC,
        max_spread_pct=settings.RISK_MAX_SPREAD_PCT,
        max_position_base=settings.RISK_MAX_POSITION_BASE,
        max_orders_per_hour=settings.RISK_MAX_ORDERS_PER_HOUR,
        daily_loss_limit_quote=settings.RISK_DAILY_LOSS_LIMIT_QUOTE,
    )
    risk = RiskManager(storage=storage, config=risk_config)
    exits = ProtectiveExits(broker=broker, storage=storage)

    # 7) Health
    health = HealthChecker(storage=storage, broker=broker, bus=bus)

    # 8) Orchestrator (как у тебя было)
    orchestrator = Orchestrator(
        symbol=settings.SYMBOL,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        settings=settings,
        # интервалы оставляем дефолт, тесты их могут ускорять
    )

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
        lock=lock,
    )
