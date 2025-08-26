## 2) `src/crypto_ai_bot/core/monitoring/health_checker.py` — ЗАМЕНА 1×1

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..storage.facade import Storage
from ..brokers.base import IBroker
from ..events.bus import AsyncEventBus
from ...utils.time import now_ms
from ...utils.logging import get_logger

_log = get_logger("health")


@dataclass
class HealthReport:
    ok: bool
    ts_ms: int
    details: Dict[str, Any]


class HealthChecker:
    """Композитная проверка готовности: БД + шина + брокер (с таймаутом).

    Если одна из проверок падает — /ready возвращает 503.
    """

    def __init__(self, *, storage: Storage, broker: IBroker, bus: AsyncEventBus, broker_timeout_sec: float = 3.0) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus
        self._broker_timeout = max(0.5, float(broker_timeout_sec))

    async def check(self, *, symbol: str) -> HealthReport:
        ts = now_ms()
        ok_db, db_err = self._check_db()
        ok_bus, bus_err = await self._check_bus()
        ok_broker, br_err = await self._check_broker(symbol)

        ok = bool(ok_db and ok_bus and ok_broker)
        details = {
            "db": {"ok": ok_db, "error": db_err},
            "bus": {"ok": ok_bus, "error": bus_err},
            "broker": {"ok": ok_broker, "error": br_err, "timeout_sec": self._broker_timeout},
        }
        if not ok:
            _log.error("health_failed", extra={"details": details})
        return HealthReport(ok=ok, ts_ms=ts, details=details)

    # --- internals ------------------------------------------------------------
    def _check_db(self) -> tuple[bool, Optional[str]]:
        try:
            cur = self._storage.conn.execute("SELECT 1")
            _ = cur.fetchone()
            cur.close()
            # schema_migrations must exist
            self._storage.conn.execute("SELECT 1 FROM schema_migrations LIMIT 1")
            return True, None
        except Exception as exc:
            return False, str(exc)

    async def _check_bus(self) -> tuple[bool, Optional[str]]:
        try:
            # простая публикация — любые исключения считаем неготовностью
            await self._bus.publish("health.ping", {"ts": now_ms()}, key="health")
            return True, None
        except Exception as exc:
            return False, str(exc)

    async def _check_broker(self, symbol: str) -> tuple[bool, Optional[str]]:
        try:
            async def _probe() -> None:
                t = await self._broker.fetch_ticker(symbol)
                if not t or (t.last is None):
                    raise RuntimeError("ticker_unavailable")
            await asyncio.wait_for(_probe(), timeout=self._broker_timeout)
            return True, None
        except Exception as exc:
            return False, str(exc)