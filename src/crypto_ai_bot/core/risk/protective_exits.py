from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

from ..storage.facade import Storage
from ..brokers.base import IBroker
from ..events.bus import AsyncEventBus
from ..brokers.symbols import parse_symbol
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ...utils.ids import make_client_order_id

_log = get_logger("risk.exits")


@dataclass
class ProtectiveExits:
    storage: Storage
    bus: AsyncEventBus

    # внутреннее состояние по символам (entry/peak/idemp)
    _state: Dict[str, Dict[str, Decimal]] = field(default_factory=dict, init=False)

    async def ensure(self, *, symbol: str, broker: IBroker, settings: "Settings") -> Optional[dict]:
        """Следит за позициями и при выполнении условий триггерит `market sell`.

        Работает в режиме long-only для spot. Идемпотентен за счёт client_order_id по бакетам времени.
        """
        try:
            pos = self.storage.positions.get_position(symbol)
            base_qty: Decimal = pos.base_qty or Decimal("0")
        except Exception as exc:
            _log.error("exits_read_position_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

        if base_qty <= 0:
            # позиция закрыта — сбрасываем локальное состояние
            self._state.pop(symbol, None)
            return None

        # параметры из Settings (безопасные дефолты)
        if not getattr(settings, "EXITS_ENABLED", True):
            return None
        mode = (getattr(settings, "EXITS_MODE", "both") or "both").lower()  # hard|trailing|both
        hard_pct = Decimal(str(getattr(settings, "EXITS_HARD_STOP_PCT", 0.05)))
        trail_pct = Decimal(str(getattr(settings, "EXITS_TRAILING_PCT", 0.03)))
        min_base = Decimal(str(getattr(settings, "EXITS_MIN_BASE_TO_EXIT", "0.00000000")))
        bucket_ms = int(getattr(settings, "IDEMPOTENCY_BUCKET_MS", 60_000))

        if min_base and base_qty < min_base:
            return None

        t = await broker.fetch_ticker(symbol)
        last = t.last

        st = self._state.setdefault(symbol, {})
        # entry устанавливаем на первом вызове при наличии позиции
        if "entry" not in st:
            st["entry"] = Decimal(last)
            st["peak"] = Decimal(last)
        # обновляем пик
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

        # идемпотентный client_order_id по бакету времени
        bucket = (now_ms() // bucket_ms) * bucket_ms
        client_id = make_client_order_id("exits", f"{symbol}:{reason}:{bucket}")

        try:
            order = await broker.create_market_sell_base(
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
            await self.bus.publish("protective_exit.triggered", payload, key=symbol)
            _log.error("protective_exit_triggered", extra=payload)
            # сбрасываем локальное состояние после выхода
            self._state.pop(symbol, None)
            return payload
        except Exception as exc:
            _log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(exc)})
            return {"error": str(exc)}