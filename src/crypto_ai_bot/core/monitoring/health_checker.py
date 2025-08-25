from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any

from ..brokers.base import IBroker
from ..storage.facade import Storage
from ...utils.time import now_ms
from ...utils.logging import get_logger

_log = get_logger("health")


@dataclass
class HealthReport:
    ok: bool
    ts_ms: int
    components: Dict[str, Any]


class HealthChecker:
    def __init__(self, *, storage: Storage, broker: IBroker, bus) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus

    async def check(self, *, symbol: str) -> HealthReport:
        comps: Dict[str, Any] = {}
        ok = True
        # DB
        try:
            cur = self._storage.conn.execute("SELECT 1")
            _ = cur.fetchone()
            comps["db"] = True
        except Exception as exc:
            comps["db"] = False
            comps["db_error"] = str(exc)
            ok = False
        # Broker ticker
        try:
            t = await self._broker.fetch_ticker(symbol)
            comps["broker_ticker"] = True if t and t.last else False
        except Exception as exc:
            comps["broker_ticker"] = False
            comps["broker_error"] = str(exc)
            ok = False
        # Bus — просто отметим доступность объекта
        comps["bus"] = self._bus is not None
        return HealthReport(ok=ok, ts_ms=now_ms(), components=comps)