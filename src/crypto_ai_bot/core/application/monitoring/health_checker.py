from __future__ import annotations

from typing import Any

from crypto_ai_bot.core.application import events_topics as evt
from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("health")


class HealthChecker:
    """
    Health checker for components:
      - DB: SELECT 1 (via storage.conn)
      - Broker: ping() or fetch_ticker on default symbol
      - Bus: test publish
    Uses only application ports, no direct infra imports.
    """

    def __init__(self, *, storage: Any, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus
        self._settings = settings
        self._symbol = getattr(settings, "SYMBOL", "BTC/USDT")
        self._dms = None  # Will be set if needed

    async def tick(self, symbol: str, dms: Any = None) -> dict[str, str]:
        """Perform health check tick."""
        self._dms = dms
        return await self.ready()

    async def ready(self) -> dict[str, str]:
        """Check readiness of all components."""
        res: dict[str, str] = {"db": "ok", "broker": "ok", "bus": "ok"}

        # DB check
        try:
            if hasattr(self._storage, "conn"):
                self._storage.conn.execute("SELECT 1;")
            elif hasattr(self._storage, "ping"):
                await self._storage.ping()
        except Exception as exc:
            _log.error("db_ready_fail", exc_info=True)
            res["db"] = f"fail:{type(exc).__name__}"

        # Broker check
        try:
            if hasattr(self._broker, "ping") and callable(self._broker.ping):
                await self._broker.ping()
            else:
                await self._broker.fetch_ticker(self._symbol)
        except Exception as exc:
            _log.error("broker_ready_fail", exc_info=True)
            res["broker"] = f"fail:{type(exc).__name__}"

        # Bus check
        try:
            if hasattr(self._bus, "publish"):
                await self._bus.publish(evt.WATCHDOG_HEARTBEAT, {"source": "health"})
        except Exception as exc:
            _log.error("bus_ready_fail", exc_info=True)
            res["bus"] = f"fail:{type(exc).__name__}"

        ok = all(v == "ok" for v in res.values())
        inc("health_ready_ok_total" if ok else "health_ready_fail_total")

        # Publish health report
        if hasattr(self._bus, "publish"):
            try:
                await self._bus.publish(evt.HEALTH_REPORT, {"ok": ok, **res})
            except Exception:
                _log.debug("health_report_publish_failed", exc_info=True)

        return res
