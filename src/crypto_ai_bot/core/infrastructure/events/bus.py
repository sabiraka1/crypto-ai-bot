from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("events.bus")


@dataclass
class AsyncEventBus:
    """Простая асинхронная «шина событий» с ретраями и логами.

    Использование:
      await bus.publish("topic", {"payload": 1}, key="BTC/USDT")
    """

    max_attempts: int = 3
    backoff_base_ms: int = 250
    backoff_factor: float = 2.0

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: Optional[str] = None) -> Dict[str, Any]:
        attempt = 1
        delay_ms = self.backoff_base_ms
        while True:
            try:
                _log.info("bus_publish", extra={"topic": topic, "key": key, "ts_ms": now_ms()})
                # no-op фолбэк: здесь может быть реальный producer (Kafka/NATS/Redis)
                return {"ok": True, "topic": topic, "key": key}
            except Exception as exc:
                if attempt >= self.max_attempts:
                    _log.error("bus_publish_failed", extra={"topic": topic, "key": key, "error": str(exc)})
                    return {"ok": False, "error": str(exc)}
                await asyncio.sleep(max(0.001, delay_ms / 1000))
                attempt += 1
                delay_ms = int(delay_ms * self.backoff_factor)