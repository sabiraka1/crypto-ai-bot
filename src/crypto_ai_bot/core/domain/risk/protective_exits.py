from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

from ..brokers.base import IBroker, OrderDTO
from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ..settings import Settings
from ...utils.logging import get_logger
from ...utils.ids import make_client_order_id
from ...utils.time import now_ms
from ...utils.metrics import inc  # ← метрики

_log = get_logger("risk.exits")


@dataclass
class ExitsPlan:
    symbol: str
    entry_price: Decimal
    sl_price: Decimal
    tp_price: Optional[Decimal]
    ts_ms: int


@dataclass
class ProtectiveExits:
    storage: Storage
    bus: AsyncEventBus
    broker: IBroker
    settings: Settings

    _state: Dict[str, Dict[str, Decimal]] = field(default_factory=dict, init=False)
    _plans: Dict[str, ExitsPlan] = field(default_factory=dict, init=False)

    async def ensure(self, *, symbol: str) -> Optional[dict]:
        try:
            pos = self.storage.positions.get_position(symbol)
            base_qty: Decimal = pos.base_qty or Decimal("0")
        except Exception as exc:
            _log.error("exits_read_position_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

        if base_qty <= 0:
            self._state.pop(symbol, None)
            return None

        if not getattr(self.settings, "EXITS_ENABLED", True):
            return None
        mode = (getattr(self.settings, "EXITS_MODE", "both") or "both").lower()
        hard_pct = Decimal(str(getattr(self.settings, "EXITS_HARD_STOP_PCT", 0.05)))
        trail_pct = Decimal(str(getattr(self.settings, "EXITS_TRAILING_PCT", 0.03)))
        min_base = Decimal(str(getattr(self.settings, "EXITS_MIN_BASE_TO_EXIT", "0.00000000")))
        bucket_ms = int(getattr(self.settings, "IDEMPOTENCY_BUCKET_MS", 60_000))

        if min_base and base_qty < min_base:
            return None

        t = await self.broker.fetch_ticker(symbol)
        last = t.last

        st = self._state.setdefault(symbol, {})
        if "entry" not in st:
            st["entry"] = Decimal(last)
            st["peak"] = Decimal(last)
        st["peak"] = max(Decimal(last), st.get("peak", Decimal(last)))

        should_sell = False
        reason = None

        if mode in ("hard", "both"):
            hard_stop_price = st["entry"] * (Decimal("1") - hard_pct)
            if last <= hard_stop_price:
                should_sell = True
                reason = f"hard_stop_{hard_pct}"

        if not should_sell and mode in ("trailing", "both"):
            trail_price = st["peak"] * (Decimal("1") - trail_pct)
            if last <= trail_price:
                should_sell = True
                reason = f"trailing_{trail_pct}"

        if not should_sell:
            return None

        bucket = (now_ms() // bucket_ms) * bucket_ms
        client_id = make_client_order_id("exits", f"{symbol}:{reason}:{bucket}")

        try:
            order = await self.broker.create_market_sell_base(
                symbol=symbol,
                base_amount=base_qty,
                client_order_id=client_id,
            )
            payload = {
                "symbol": symbol,
                "base_sold": str(base_qty),
                "price": str(last),
                "reason": reason,
                "order_id": getattr(order, "id", None),
                "client_order_id": client_id,
                "ts": now_ms(),
            }
            inc("exits_triggered_total", reason=(reason or "na"))  # ← метрика
            await self.bus.publish("protective_exit.triggered", payload, key=symbol)
            _log.warning("protective_exit_triggered", extra=payload)
            self._state.pop(symbol, None)
            return payload
        except Exception as exc:
            _log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(exc)})
            return {"error": str(exc)}

    async def check_and_execute(self, *, symbol: str) -> Optional[OrderDTO]:
        plan = self._plans.get(symbol)
        if not plan:
            return None
        pos = self.storage.positions.get_position(symbol)
        base_qty = pos.base_qty or Decimal("0")
        if base_qty <= 0:
            return None
        t = await self.broker.fetch_ticker(symbol)
        last = t.last or t.bid or t.ask
        if not last or last <= 0:
            return None
        if plan.sl_price and last <= plan.sl_price:
            return await self.broker.create_market_sell_base(symbol=symbol, base_amount=base_qty, client_order_id=make_client_order_id("sl", symbol))
        if plan.tp_price and last >= plan.tp_price:
            return await self.broker.create_market_sell_base(symbol=symbol, base_amount=base_qty, client_order_id=make_client_order_id("tp", symbol))
        return None
