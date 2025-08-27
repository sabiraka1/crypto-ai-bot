from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ..brokers.base import IBroker
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("health")


@dataclass
class HealthReport:
    ok: bool
    ts_ms: int
    components: Dict[str, Any]  # ✅ было details


class HealthChecker:
    def __init__(self, *, storage: Storage, broker: IBroker, bus: AsyncEventBus) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus

    async def check(self, *, symbol: str) -> HealthReport:
        ts = now_ms()
        ok_db, db_err = self._check_db()
        ok_bus, bus_err = await self._check_bus()
        ok_broker, br_err = await self._check_broker(symbol)

        ok = bool(ok_db and ok_bus and ok_broker)
        return HealthReport(
            ok=ok,
            ts_ms=ts,
            components={
                "db": {"ok": ok_db, "error": db_err},
                "bus": {"ok": ok_bus, "error": bus_err},
                "broker": {"ok": ok_broker, "error": br_err},
            },
        )

    def _check_db(self) -> Tuple[bool, str]:
        try:
            self._storage.conn.execute("SELECT 1")
            return True, ""
        except Exception as exc:
            return False, str(exc)

    async def _check_bus(self) -> Tuple[bool, str]:
        try:
            await self._bus.publish("health.ping", {"ok": True}, key="ping")
            return True, ""
        except Exception as exc:
            return False, str(exc)

    async def _check_broker(self, symbol: str) -> Tuple[bool, str]:
        try:
            t = await self._broker.fetch_ticker(symbol)
            return (t.last is not None and t.last > 0), ""
        except Exception as exc:
            return False, str(exc)
