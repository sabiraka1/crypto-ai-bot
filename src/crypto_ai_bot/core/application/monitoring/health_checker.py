# src/crypto_ai_bot/core/application/monitoring/health_checker.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("health")


@dataclass
class HealthReport:
    ok: bool
    ts_ms: int
    components: Dict[str, Any]


class HealthChecker:
    def __init__(self, *, storage: Storage, broker: IBroker, bus: AsyncEventBus) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus

    async def check(self, *, symbol: str) -> HealthReport:
        ts = now_ms()
        ok_db, db_err = self._check_db()
        ok_schema, sch_err, sch = self._check_schema()
        ok_bus, bus_err = await self._check_bus()
        ok_broker, br_err, last = await self._check_broker(symbol)

        ok = bool(ok_db and ok_schema and ok_bus and ok_broker)
        return HealthReport(
            ok=ok,
            ts_ms=ts,
            components={
                "db": {"ok": ok_db, "error": db_err},
                "schema": {"ok": ok_schema, "error": sch_err, "tables": sch},
                "bus": {"ok": ok_bus, "error": bus_err},
                "broker": {"ok": ok_broker, "error": br_err, "last": (str(last) if last is not None else None), "symbol": symbol},
            },
        )

    def _check_db(self) -> Tuple[bool, str]:
        try:
            self._storage.conn.execute("SELECT 1")
            return True, ""
        except Exception as exc:
            _log.error("db_check_failed", extra={"error": str(exc)})
            return False, str(exc)

    def _check_schema(self) -> Tuple[bool, str, Dict[str, bool]]:
        """Проверяем, что ключевые таблицы существуют (миграции применены)."""
        required = ("positions", "trades", "audit", "idempotency", "market_data", "instance_lock")
        status: Dict[str, bool] = {}
        ok_all = True
        err = ""
        try:
            for t in required:
                cur = self._storage.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (t,)
                )
                exists = cur.fetchone() is not None
                status[t] = bool(exists)
                ok_all = ok_all and exists
            return ok_all, err, status
        except Exception as exc:
            err = str(exc)
            _log.error("schema_check_failed", extra={"error": err})
            return False, err, status

    async def _check_bus(self) -> Tuple[bool, str]:
        try:
            await self._bus.publish("health.ping", {"ok": True}, key="ping")
            return True, ""
        except Exception as exc:
            _log.error("bus_check_failed", extra={"error": str(exc)})
            return False, str(exc)

    async def _check_broker(self, symbol: str) -> Tuple[bool, str, Any]:
        try:
            t = await self._broker.fetch_ticker(symbol)
            ok = (t.last is not None and t.last > 0)
            return ok, "" if ok else "no_last_price", (t.last if ok else None)
        except Exception as exc:
            _log.error("broker_check_failed", extra={"error": str(exc)})
            return False, str(exc), None
