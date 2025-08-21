## `core/risk/protective_exits.py`
from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Dict, Optional
from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ..events import topics
from ..brokers.base import OrderDTO
from ...utils.time import now_ms
from ...utils.logging import get_logger
_log = get_logger("risk.protective_exits")
@dataclass(frozen=True)
class ExitPolicy:
    take_profit_pct: float = 2.0   # +2%
    stop_loss_pct: float = 1.5     # -1.5%
@dataclass(frozen=True)
class ExitPlan:
    symbol: str
    entry_price: str   # сохраняем как str для Decimal‑безопасности
    amount: str        # base amount
    tp_price: str
    sl_price: str
    client_order_id: str
    created_at_ms: int
class ProtectiveExits:
    """Фиксация TP/SL‑плана в журнале аудита (без выделенной таблицы).
    ensure(): создаёт план на основе выполненного BUY‑ордера.
    get_latest_plan(): возвращает последний план по символу (по audit_log).
    """
    def __init__(self, storage: Storage, policy: ExitPolicy | None = None, bus: AsyncEventBus | None = None):
        self.storage = storage
        self.policy = policy or ExitPolicy()
        self.bus = bus
    async def ensure(self, *, symbol: str, order: OrderDTO) -> ExitPlan | None:
        if order.side != "buy" or order.price <= 0:
            return None
        p = Decimal(str(order.price))
        amt = Decimal(str(order.amount))
        tp = p * (Decimal("1") + Decimal(self.policy.take_profit_pct) / Decimal("100"))
        sl = p * (Decimal("1") - Decimal(self.policy.stop_loss_pct) / Decimal("100"))
        plan = ExitPlan(
            symbol=symbol,
            entry_price=str(p),
            amount=str(amt),
            tp_price=str(tp),
            sl_price=str(sl),
            client_order_id=order.client_order_id,
            created_at_ms=now_ms(),
        )
        self._save_plan(plan)
        if self.bus:
            await self.bus.publish(
                topics.PROTECTIVE_EXIT_UPDATED,
                {"symbol": symbol, "client_order_id": order.client_order_id, "tp": plan.tp_price, "sl": plan.sl_price},
                key=symbol,
            )
        return plan
    def _save_plan(self, plan: ExitPlan) -> int:
        return self.storage.audit.log("protective_exit.created", asdict(plan))
    def get_latest_plan(self, symbol: str) -> Optional[ExitPlan]:
        for _id, action, payload, _ts in self.storage.audit.list_recent(limit=200):
            if action != "protective_exit.created":
                continue
            if payload.get("symbol") == symbol:
                try:
                    return ExitPlan(**payload)
                except Exception:
                    continue
        return None