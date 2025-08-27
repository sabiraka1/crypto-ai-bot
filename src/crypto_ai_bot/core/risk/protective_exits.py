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

    # внутреннее состояние по символам (entry/peak/idemp)
    _state: Dict[str, Dict[str, Decimal]] = field(default_factory=dict, init=False)
    # in-memory планов по символам (если у вас уже есть персист — это не мешает)
    _plans: Dict[str, ExitsPlan] = field(default_factory=dict, init=False)

    async def ensure(self, *, symbol: str) -> Optional[dict]:
        """
        Следит за позициями и при выполнении условий триггерит `market sell`.
        Работает в режиме long-only для spot. Идемпотентен за счёт client_order_id по бакетам времени.
        """
        # позиция
        try:
            pos = self.storage.positions.get_position(symbol)
            base_qty: Decimal = pos.base_qty or Decimal("0")
        except Exception as exc:
            _log.error("exits_read_position_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

        # если позиции нет — сбрасываем локальный state и выходим
        if base_qty <= 0:
            self._state.pop(symbol, None)
            return None

        # параметры из Settings (безопасные дефолты)
        if not getattr(self.settings, "EXITS_ENABLED", True):
            return None
        mode = (getattr(self.settings, "EXITS_MODE", "both") or "both").lower()  # hard|trailing|both
        hard_pct = Decimal(str(getattr(self.settings, "EXITS_HARD_STOP_PCT", 0.05)))
        trail_pct = Decimal(str(getattr(self.settings, "EXITS_TRAILING_PCT", 0.03)))
        min_base = Decimal(str(getattr(self.settings, "EXITS_MIN_BASE_TO_EXIT", "0.00000000")))
        bucket_ms = int(getattr(self.settings, "IDEMPOTENCY_BUCKET_MS", 60_000))

        if min_base and base_qty < min_base:
            return None

        # текущая цена
        t = await self.broker.fetch_ticker(symbol)
        last = t.last

        # инициализация внутреннего состояния
        st = self._state.setdefault(symbol, {})
        if "entry" not in st:
            st["entry"] = Decimal(last)
            st["peak"] = Decimal(last)
        # обновляем пик
        st["peak"] = max(Decimal(last), st.get("peak", Decimal(last)))

        # логика триггеров
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
            await self.bus.publish("protective_exit.triggered", payload, key=symbol)
            _log.warning("protective_exit_triggered", extra=payload)
            # сбрасываем локальное состояние после выхода
            self._state.pop(symbol, None)
            return payload
        except Exception as exc:
            _log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(exc)})
            return {"error": str(exc)}

    async def check_and_execute(self, *, symbol: str) -> Optional[OrderDTO]:
        """
        Проверяет достижение SL/TP по заранее заданному плану (если он есть)
        и исполняет рыночный SELL при наличии позиции. Возвращает OrderDTO или None.
        """
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

        # Stop Loss
        if plan.sl_price and last <= plan.sl_price:
            cid = make_client_order_id("sl", symbol)
            _log.warning("stop_loss_triggered", extra={"symbol": symbol, "price": str(last), "sl": str(plan.sl_price), "qty": str(base_qty)})
            return await self.broker.create_market_sell_base(symbol=symbol, base_amount=base_qty, client_order_id=cid)

        # Take Profit
        if plan.tp_price and last >= plan.tp_price:
            cid = make_client_order_id("tp", symbol)
            _log.info("take_profit_triggered", extra={"symbol": symbol, "price": str(last), "tp": str(plan.tp_price), "qty": str(base_qty)})
            return await self.broker.create_market_sell_base(symbol=symbol, base_amount=base_qty, client_order_id=cid)

        return None
