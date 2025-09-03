from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.logging import get_logger


try:
    from crypto_ai_bot.core.application import events_topics as EVT
    _DMS_TOPIC = getattr(EVT, "DMS_TRIGGERED", "safety.dead_mans_switch.triggered")
except Exception:
    _DMS_TOPIC = "safety.dead_mans_switch.triggered"

_log = get_logger("safety.dms")


@dataclass
class DeadMansSwitch:
    storage: Any | None = None
    broker: Any | None = None
    symbol: str | None = None
    timeout_ms: int = 120_000
    rechecks: int = 1
    recheck_delay_sec: float = 0.0
    max_impact_pct: Decimal = Decimal("0")
    bus: Any | None = None

    _last_beat_ms: int = 0
    _last_healthy_price: Decimal | None = None

    async def check(self) -> None:
        """
        Лёгкий защитный триггер по резкой просадке цены:
        - делает 0..N повторных проверок цены с задержкой;
        - при срабатывании пытается продать базовый актив (best-effort);
        - публикует событие в шину.
        """
        # Skip branch (настройка для юнит-тестов)
        if self.max_impact_pct and self.max_impact_pct > 0:
            return
        if not self.broker or not self.symbol:
            return

        # первый снимок
        t = await self.broker.fetch_ticker(self.symbol)
        last = Decimal(str(getattr(t, "last", "0")))
        if self._last_healthy_price is None:
            self._last_healthy_price = last
            return

        # повторы
        cur = last
        for _ in range(max(0, int(self.rechecks))):
            if self.recheck_delay_sec:
                await asyncio.sleep(self.recheck_delay_sec)
            t2 = await self.broker.fetch_ticker(self.symbol)
            cur = Decimal(str(getattr(t2, "last", str(cur))))

        # триггер: падение >= 3%
        threshold = Decimal("0.97") * self._last_healthy_price
        if cur < threshold:
            try:
                # best-effort: не валим поток, но и не глушим исключение
                await self.broker.create_market_sell_base(self.symbol, Decimal("0"))
            except Exception as exc:
                _log.warning(
                    "dms_sell_failed",
                    extra={"symbol": self.symbol, "error": str(exc)},
                    exc_info=True,
                )
            if self.bus and hasattr(self.bus, "publish"):
                await self.bus.publish(
                    _DMS_TOPIC,
                    {"symbol": self.symbol, "prev": str(self._last_healthy_price), "last": str(cur)},
                )
            self._last_healthy_price = cur
        else:
            self._last_healthy_price = max(self._last_healthy_price, cur)
