from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, getcontext
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

    # миграции + бэкап
    retention = int(os.getenv("BACKUP_RETENTION_D
