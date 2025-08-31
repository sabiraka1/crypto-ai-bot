from __future__ import annotations

from typing import Any, Optional

try:
    from crypto_ai_bot.utils.logging import get_logger
except Exception:  # pragma: no cover
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

try:
    from crypto_ai_bot.utils.metrics import inc
except Exception:  # pragma: no cover
    def inc(_name: str, **_labels: Any) -> None:
        pass

_log = get_logger("monitoring.health")


class HealthChecker:
    """
    Лёгкий «пульс» системы: проверка доступности ключевых зависимостей.
    Никаких блокирующих действий, только best-effort и метрики/ивенты.

    Контракты:
      - storage: желательно иметь .ping() -> bool; если нет — допустимо, чтобы был .conn с .execute("select 1")
      - broker: должен уметь fetch_ticker(symbol)
      - bus: допускается publish(topic, payload)
    """

    def __init__(self, *, storage: Any, broker: Any, bus: Any, settings: Any) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus
        self._settings = settings

    # основной API — синхронизирован с оркестратором
    async def tick(self, symbol: str, *, dms: Optional[Any] = None) -> None:
        ok_storage = self._check_storage()
        ok_broker = await self._check_broker(symbol)
        ok_bus = await self._check_bus()

        overall = ok_storage and ok_broker and ok_bus
        inc("health_tick_ok_total" if overall else "health_tick_fail_total", symbol=symbol)

        if not overall and dms is not None:
            # dms — безопасный best-effort: решает сам, что делать (продать базовый, если всё плохо)
            try:
                await dms.on_health_degraded(symbol=symbol, ok_storage=ok_storage, ok_broker=ok_broker, ok_bus=ok_bus)
            except Exception:
                _log.error("dms_on_health_degraded_failed", extra={"symbol": symbol}, exc_info=True)

    # ---- частные проверки ----

    def _check_storage(self) -> bool:
        try:
            # 1) предпочтительно: ping()
            ping = getattr(self._storage, "ping", None)
            if callable(ping):
                if bool(ping()):
                    return True
                _log.warning("storage_ping_false")
                return False

            # 2) допустимо: низкоуровневый SELECT 1
            conn = getattr(self._storage, "conn", None)
            if conn is not None and hasattr(conn, "execute"):
                try:
                    conn.execute("SELECT 1;")
                    return True
                except Exception:
                    _log.error("storage_select1_failed", exc_info=True)
                    return False

            # 3) ничего не умеем — считаем ок (не блокируем)
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
            # Доп. эвристики можно добавить (bid/ask/last > 0), но оставим мягко
            if t is None:
                _log.warning("broker_fetch_ticker_none", extra={"symbol": symbol})
                return False
            return True
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
