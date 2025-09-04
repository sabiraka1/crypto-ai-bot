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
      - DB: SELECT 1 (via storage.conn) или storage.ping()
      - Broker: ping() или fetch_ticker на базовом символе
      - Bus: пробная публикация события
    Использует только application ports (без прямых импортов инфраструктуры).
    """

    def __init__(self, *, storage: Any, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
        self._storage = storage
        self._broker = broker
        self._bus = bus
        self._settings = settings
        self._symbol = getattr(settings, "SYMBOL", "BTC/USDT")
        self._dms = None  # будет установлен при необходимости

    async def tick(self, symbol: str, dms: Any = None) -> dict[str, str]:
        """
        Один тик watchdog: опционально дергаем DMS и возвращаем готовность компонентов.
        DMS не влияет на статус готовности; он защитный.
        """
        self._dms = dms
        # Dead Man’s Switch (если передан)
        try:
            if self._dms and hasattr(self._dms, "check"):
                await self._dms.check()
        except Exception:  # noqa: BLE001
            _log.warning("dms_check_failed", exc_info=True)

        return await self.ready()

    async def ready(self) -> dict[str, str]:
        """Проверить готовность всех базовых компонентов и опубликовать отчёт."""
        res: dict[str, str] = {
            "db": await self._check_db(),
            "broker": await self._check_broker(),
            "bus": await self._check_bus(),
        }

        ok = all(v == "ok" for v in res.values())
        inc("health_ready_ok_total" if ok else "health_ready_fail_total")

        # Публикуем health-репорт (не падаем, если шина недоступна)
        if hasattr(self._bus, "publish"):
            try:
                await self._bus.publish(evt.HEALTH_REPORT, {"ok": ok, **res})
            except Exception:  # noqa: BLE001
                _log.debug("health_report_publish_failed", exc_info=True)

        return res

    # ----------------- helpers -----------------
    async def _check_db(self) -> str:
        """DB: storage.conn.execute('SELECT 1') или storage.ping()."""
        try:
            if hasattr(self._storage, "conn") and getattr(self._storage, "conn") is not None:
                # Синхронная проверка — лёгкий запрос
                self._storage.conn.execute("SELECT 1;")
                return "ok"
            if hasattr(self._storage, "ping"):
                await self._storage.ping()
                return "ok"
            # Если нет ни conn, ни ping — считаем ОК (нет БД в конфигурации)
            return "ok"
        except (ConnectionError, TimeoutError) as exc:
            _log.error("db_ready_conn_timeout", exc_info=True)
            return f"fail:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            _log.error("db_ready_fail", exc_info=True)
            return f"fail:{type(exc).__name__}"

    async def _check_broker(self) -> str:
        """Broker: broker.ping() или fetch_ticker(self._symbol)."""
        try:
            if hasattr(self._broker, "ping") and callable(self._broker.ping):
                await self._broker.ping()
                return "ok"
            await self._broker.fetch_ticker(self._symbol)
            return "ok"
        except (ConnectionError, TimeoutError) as exc:
            _log.error("broker_ready_conn_timeout", exc_info=True)
            return f"fail:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            _log.error("broker_ready_fail", exc_info=True)
            return f"fail:{type(exc).__name__}"

    async def _check_bus(self) -> str:
        """Bus: пробная публикация WATCHDOG_HEARTBEAT."""
        try:
            if hasattr(self._bus, "publish") and callable(self._bus.publish):
                await self._bus.publish(evt.WATCHDOG_HEARTBEAT, {"source": "health"})
            return "ok"
        except (ConnectionError, TimeoutError) as exc:
            _log.error("bus_ready_conn_timeout", exc_info=True)
            return f"fail:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            _log.error("bus_ready_fail", exc_info=True)
            return f"fail:{type(exc).__name__}"
