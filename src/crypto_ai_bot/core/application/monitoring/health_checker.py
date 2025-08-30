from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.utils.metrics import observe
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("monitoring.health_checker")


@dataclass
class HealthChecker:
    storage: StoragePort
    broker: BrokerPort
    bus: EventBusPort
    symbol: str

    async def check(self) -> Dict[str, Any]:
        t0 = time.time()
        ok = True
        errors: List[str] = []

        # Лёгкая проверка хранилища
        try:
            _ = self.storage.positions.get_position(self.symbol)
        except Exception as e:
            ok = False
            errors.append(f"storage:{e}")

        # Лёгкая проверка брокера (тикер)
        try:
            t1 = time.time()
            await self.broker.fetch_ticker(self.symbol)
            observe("health.broker.ms", (time.time() - t1) * 1000.0)
        except Exception as e:
            ok = False
            errors.append(f"broker:{e}")

        # Heartbeat всегда публикуем (если шина доступна)
        try:
            await self.bus.publish("watchdog.heartbeat", {"symbol": self.symbol, "ok": ok})
        except Exception as e:
            ok = False
            errors.append(f"bus:{e}")

        observe("health.total.ms", (time.time() - t0) * 1000.0)
        if not ok:
            _log.warning("health_unhealthy", extra={"symbol": self.symbol, "errors": errors})
        return {"ok": ok, "errors": errors}
