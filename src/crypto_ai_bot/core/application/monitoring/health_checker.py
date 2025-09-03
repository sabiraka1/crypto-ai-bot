from __future__ import annotations
import asyncio
from typing import Any, Dict, Optional

from crypto_ai_bot.core.application import events_topics as EVT
from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("health")


class HealthChecker:
    """
    Простые проверки состояния компонентов:
      - DB: SELECT 1
      - Broker: легкий вызов (fetch_ticker на дефолтном символе) или ping(), если доступно
      - Bus: пробный publish без исключения
    """

    def __init__(self, *, storage: Storage, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
        self._st = storage
        self._br = broker
        self._bus = bus
        self._s = settings
        self._symbol = getattr(settings, "SYMBOL", "BTC/USDT")

    async def ready(self) -> Dict[str, str]:
        res: Dict[str, str] = {"db": "ok", "broker": "ok", "bus": "ok"}
        # DB
        try:
            self._st.conn.execute("SELECT 1;")
        except Exception as e:
            _log.error("db_ready_fail", exc_info=True)
            res["db"] = f"db:{type(e).__name__}"

        # Broker
        try:
            if hasattr(self._br, "ping") and callable(getattr(self._br, "ping")):
                await self._br.ping()
            else:
                await self._br.fetch_ticker(self._symbol)
        except Exception as e:
            _log.error("broker_ready_fail", exc_info=True)
            res["broker"] = f"broker:{type(e).__name__}"

        # Bus
        try:
            if hasattr(self._bus, "publish"):
                await self._bus.publish(EVT.WATCHDOG_HEARTBEAT, {"source": "health", "ts": None})
        except Exception as e:
            _log.error("bus_ready_fail", exc_info=True)
            res["bus"] = f"bus:{type(e).__name__}"

        ok = all(v == "ok" for v in res.values())
        if not ok and hasattr(self._bus, "publish"):
            try:
                await self._bus.publish(EVT.HEALTH_REPORT, {"ok": False, **res})
            except Exception:
                pass
        if ok:
            inc("health_ready_ok_total")
        else:
            inc("health_ready_fail_total")

        return res
