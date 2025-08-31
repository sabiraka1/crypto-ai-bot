from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    from crypto_ai_bot.utils.logging import get_logger
except Exception:
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

try:
    from crypto_ai_bot.utils.metrics import inc
except Exception:
    def inc(_name: str, **_labels: Any) -> None:
        pass

_log = get_logger("monitoring.health")


class HealthChecker:
    def __init__(self, *, storage: Any, broker: Any, bus: Any, settings: Any) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus
        self._settings = settings
        self._last: dict[str, Any] = {"ts": None, "ok_storage": None, "ok_broker": None, "ok_bus": None}

    def get_snapshot(self) -> dict[str, Any]:
        return dict(self._last)

    async def tick(self, symbol: str, *, dms: Any | None = None) -> None:
        ok_storage = self._check_storage()
        ok_broker = await self._check_broker(symbol)
        ok_bus = await self._check_bus()

        overall = ok_storage and ok_broker and ok_bus
        inc("health_tick_ok_total" if overall else "health_tick_fail_total", symbol=symbol)

        self._last = {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "ok_storage": ok_storage,
            "ok_broker": ok_broker,
            "ok_bus": ok_bus,
        }

        if not overall and dms is not None:
            try:
                await dms.on_health_degraded(symbol=symbol, ok_storage=ok_storage, ok_broker=ok_broker, ok_bus=ok_bus)
            except Exception:
                _log.error("dms_on_health_degraded_failed", extra={"symbol": symbol}, exc_info=True)

    def _check_storage(self) -> bool:
        try:
            ping = getattr(self._storage, "ping", None)
            if callable(ping):
                return bool(ping())
            conn = getattr(self._storage, "conn", None)
            if conn is not None and hasattr(conn, "execute"):
                conn.execute("SELECT 1;")
                return True
            _log.info("storage_ping_not_supported")
            return True
        except Exception:
            _log.error("storage_check_exception", exc_info=True)
            return False

    async def _check_broker(self, symbol: str) -> bool:
        try:
            fetch_ticker = getattr(self._broker, "fetch_ticker", None)
            if not callable(fetch_ticker):
                _log.info("broker_fetch_ticker_not_supported")
                return True
            t = await fetch_ticker(symbol)
            return t is not None
        except Exception:
            _log.error("broker_fetch_ticker_failed", extra={"symbol": symbol}, exc_info=True)
            try:
                await self._bus.publish("broker.error", {"symbol": symbol, "error": "fetch_ticker_exception"})
            except Exception:
                _log.error("broker_error_event_publish_failed", exc_info=True)
            return False

    async def _check_bus(self) -> bool:
        try:
            pub = getattr(self._bus, "publish", None)
            if not callable(pub):
                _log.info("bus_publish_not_supported")
                return True
            await pub("health.heartbeat", {"ok": True})
            return True
        except Exception:
            _log.error("bus_publish_failed", exc_info=True)
            return False
