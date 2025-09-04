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
    storage: Any | None = None  # ожидается storage.positions.get_position(symbol)
    broker: Any | None = None
    symbol: str | None = None
    timeout_ms: int = 120_000
    rechecks: int = 1
    recheck_delay_sec: float = 0.0
    max_impact_pct: Decimal = Decimal("3")  # порог просадки в %
    bus: Any | None = None

    _last_healthy_price: Decimal | None = None

    async def _current_price(self) -> Decimal:
        t = await self.broker.fetch_ticker(self.symbol)  # type: ignore[arg-type]
        return Decimal(str(getattr(t, "last", t.get("last", "0"))))  # type: ignore[union-attr]

    def _current_base_qty(self) -> Decimal:
        # 1) из стораджа (точнее — позиция по символу)
        try:
            if self.storage and hasattr(self.storage, "positions"):
                pos = self.storage.positions.get_position(self.symbol)  # type: ignore[union-attr]
                if pos:
                    q = getattr(pos, "base_qty", None)
                    if q is not None:
                        return Decimal(str(q))
        except Exception:
            _log.exception("dms_read_position_failed", extra={"symbol": self.symbol})

        # 2) fallback — свободный баланс у брокера (может отличаться от позиции)
        try:
            bal = asyncio.get_event_loop().run_until_complete(self.broker.fetch_balance(self.symbol))  # type: ignore[arg-type]
        except RuntimeError:
            # если уже в event loop — лучше игнорировать fallback и не блокировать
            return Decimal("0")
        except Exception:
            return Decimal("0")

        base_ccy = (self.symbol or "XXX/YYY").split("/")[0]
        free_base = bal.get("free_base")
        try:
            return Decimal(str(free_base)) if free_base is not None else Decimal("0")
        except Exception:
            return Decimal("0")

    async def check(self) -> None:
        if not self.broker or not self.symbol:
            return

        last = await self._current_price()
        if self._last_healthy_price is None:
            self._last_healthy_price = last
            return

        cur = last
        for _ in range(max(0, int(self.rechecks))):
            if self.recheck_delay_sec:
                await asyncio.sleep(self.recheck_delay_sec)
            cur = await self._current_price()

        threshold = (Decimal("100") - self.max_impact_pct) / Decimal("100") * self._last_healthy_price
        if cur < threshold:
            qty = self._current_base_qty()
            if qty > 0:
                try:
                    await self.broker.create_market_sell_base(symbol=self.symbol, base_amount=qty)  # type: ignore[arg-type]
                except Exception as exc:
                    _log.warning(
                        "dms_sell_failed", extra={"symbol": self.symbol, "error": str(exc)}, exc_info=True
                    )
            if self.bus and hasattr(self.bus, "publish"):
                await self.bus.publish(
                    _DMS_TOPIC,
                    {
                        "symbol": self.symbol,
                        "prev": str(self._last_healthy_price),
                        "last": str(cur),
                        "qty": str(qty),
                    },
                )
            self._last_healthy_price = cur
        else:
            # Обновляем "здоровую" цену до макс(предыдущая, текущая)
            self._last_healthy_price = max(self._last_healthy_price, cur)
