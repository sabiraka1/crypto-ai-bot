from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from ..utils.logging import get_logger
from ..utils.time import now_ms
from ..core.settings import Settings
from ..core.events.bus import AsyncEventBus
from ..core.storage.facade import Storage
from ..core.storage.migrations.runner import run_migrations
from ..core.monitoring.health_checker import HealthChecker
from ..core.risk.manager import RiskManager, RiskConfig
from ..core.risk.protective_exits import ProtectiveExits
from ..core.orchestrator import Orchestrator
from ..core.brokers.base import IBroker
from ..core.alerts.reconcile_stale import attach as attach_reconcile_alerts
from ..core.monitoring.dlq_subscriber import attach as attach_dlq

# брокеры
from ..core.brokers.ccxt_exchange import CcxtBroker  # live
from ..core.brokers.paper import PaperBroker         # paper

# безопасность/устойчивость
from ..core.safety.instance_lock import InstanceLock
from ..core.safety.dead_mans_switch import DeadMansSwitch

# reconciliation-скелеты
from ..core.reconciliation import (
    PositionsReconciler,
    OrdersReconciler,
    BalancesReconciler,
)

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


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_storage_for_mode(settings: Settings) -> Storage:
    conn = _connect(settings.DB_PATH)
    # миграции (включая индексы) — пройдут повторно безопасно
    run_migrations(conn, now_ms=now_ms())
    storage = Storage.from_connection(conn)
    _log.info("storage_ready", extra={"db_path": settings.DB_PATH})
    return storage


def _create_broker_for_mode(settings: Settings, storage: Storage) -> IBroker:
    if settings.MODE == "live":
        _log.info("creating_live_broker", extra={"exchange": settings.EXCHANGE})
        return CcxtBroker(
            exchange_id=settings.EXCHANGE,
            api_key=settings.API_KEY,
            api_secret=settings.API_SECRET,
        )
    # paper
    _log.info("creating_paper_broker", extra={"balances": {"USDT": "10000"}})
    return PaperBroker(quote_balance_init="10000")  # безопасные дефолты


def build_container() -> Container:
    """Сборка контейнера с безопасной интеграцией Lock/DMS/Reconcile."""
    settings = Settings.load()

    _log.info(
        "building_container",
        extra={"mode": settings.MODE, "exchange": settings.EXCHANGE, "symbol": settings.SYMBOL},
    )

    # storage + миграции
    storage = _create_storage_for_mode(settings)

    # event bus
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=250, backoff_factor=2.0)
    
    # Подключение подписчика на reconcile события
    attach_reconcile_alerts(bus)
    
    # Подключение подписчика на DLQ события для мониторинга
    attach_dlq(bus)

    # broker
    broker = _create_broker_for_mode(settings, storage)

    # risk
    risk = RiskManager(
        storage=storage,
        config=RiskConfig(
            cooldown_sec=30,
            max_spread_pct=0.3,
            # Остальные поля RiskConfig читаются из дефолтов/ENV внутри RiskConfig при необходимости
        ),
    )

    # exits
    exits = ProtectiveExits(storage=storage, broker=broker, bus=bus)

    # health
    health = HealthChecker(storage=storage, broker=broker, bus=bus)

    # --- safety: lock (только для LIVE), тихо/без фаталов ---
    if settings.MODE == "live":
        try:
            lock = InstanceLock(storage.conn, name="trading-bot")
            if not lock.acquire(ttl_sec=300):
                _log.error("instance_lock_not_acquired")
            else:
                _log.info("instance_lock_acquired")
        except Exception as exc:
            _log.error("instance_lock_error", extra={"error": str(exc)})

    # Dead Man's Switch (и в paper, и в live — без побочных эффектов)
    dms = DeadMansSwitch(storage=storage, broker=broker)

    # Reconcilers (мягкие, без критичных действий)
    reconcilers = [
        PositionsReconciler(storage=storage, exits=exits, symbol=settings.SYMBOL),
        OrdersReconciler(storage=storage, broker=broker, symbol=settings.SYMBOL),
        BalancesReconciler(broker=broker),
    ]

    # orchestrator
    orc = Orchestrator(
        symbol=settings.SYMBOL,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        settings=settings,
        dms=dms,
        reconcilers=reconcilers,
    )

    _log.info(
        "container_built",
        extra={"mode": settings.MODE, "components": ["settings", "storage", "broker", "bus", "health", "risk", "exits", "orchestrator"]},
    )

    return Container(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        health=health,
        risk=risk,
        exits=exits,
        orchestrator=orc,
    )