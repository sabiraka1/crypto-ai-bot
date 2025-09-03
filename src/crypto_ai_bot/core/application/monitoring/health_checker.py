from __future__ import annotations

from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("health")


class HealthChecker:
    """
    РџСЂРѕРІРµСЂРєРё РєРѕРјРїРѕРЅРµРЅС‚:
      - DB: SELECT 1 (С‡РµСЂРµР· storage.conn)
      - Broker: ping() РёР»Рё fetch_ticker РЅР° РґРµС„РѕР»С‚РЅРѕРј СЃРёРјРІРѕР»Рµ
      - Bus: РїСЂРѕР±РЅС‹Р№ publish
    РўРѕР»СЊРєРѕ application-РїРѕСЂС‚С‹, Р±РµР· РїСЂСЏРјС‹С… РёРјРїРѕСЂС‚РѕРІ infra-РєР»Р°СЃСЃРѕРІ.
    """

    def __init__(self, *, storage: Any, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
        self._st = storage
        self._br = broker
        self._bus = bus
        self._s = settings
        self._symbol = getattr(settings, "SYMBOL", "BTC/USDT")

    async def ready(self) -> dict[str, str]:
        res: dict[str, str] = {"db": "ok", "broker": "ok", "bus": "ok"}

        # DB
        try:
            self._st.conn.execute("SELECT 1;")
        except Exception as e:  # noqa: BLE001
            _log.error("db_ready_fail", exc_info=True)
            res["db"] = f"db:{type(e).__name__}"

        # Broker
        try:
            if hasattr(self._br, "ping") and callable(self._br.ping):
                await self._br.ping()
            else:
                await self._br.fetch_ticker(self._symbol)
        except Exception as e:  # noqa: BLE001
            _log.error("broker_ready_fail", exc_info=True)
            res["broker"] = f"broker:{type(e).__name__}"

        # Bus
        try:
            if hasattr(self._bus, "publish"):
                await self._bus.publish("watchdog.heartbeat", {"source": "health"})
        except Exception as e:  # noqa: BLE001
            _log.error("bus_ready_fail", exc_info=True)
            res["bus"] = f"bus:{type(e).__name__}"

        ok = all(v == "ok" for v in res.values())
        inc("health_ready_ok_total" if ok else "health_ready_fail_total")
        return res

    async def tick(self) -> dict[str, str]:
        return await self.ready()
