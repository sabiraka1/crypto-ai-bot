## `core/risk/manager.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple
from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ..events import topics
from ...utils.time import now_ms
from ...utils.logging import get_logger
_log = get_logger("risk.manager")
@dataclass(frozen=True)
class RiskConfig:
    cooldown_sec: int = 30            # минимальная пауза между сделками по символу
    max_spread_pct: float = 0.3       # не торговать при слишком широком спреде (в процентах)
    allow_pyramiding: bool = True     # разрешать ли докупать при открытой позиции
class RiskManager:
    """Минимальный, но практичный риск-менеджер.
    Правила:
      1) SELL запрещён, если нет позиции.
      2) Покупка/продажа блокируются, если с момента последней сделки прошло < cooldown_sec.
      3) Любое действие блокируется, если текущий spread_pct > max_spread_pct.
    """
    def __init__(self, storage: Storage, config: RiskConfig | None = None, bus: AsyncEventBus | None = None):
        self.storage = storage
        self.config = config or RiskConfig()
        self.bus = bus
    async def check(self, *, symbol: str, action: str, evaluation) -> Tuple[bool, str]:
        if action == "sell":
            if self.storage.positions.get_base_qty(symbol) <= Decimal("0"):
                return False, "no_position"
        last = self._last_trade_ts_ms(symbol)
        if last is not None:
            if (now_ms() - last) < (self.config.cooldown_sec * 1000):
                return False, "cooldown_active"
        spread_pct = float(evaluation.features.get("spread_pct", 0.0))
        if spread_pct > self.config.max_spread_pct:
            return False, "spread_too_wide"
        return True, "ok"
    def _last_trade_ts_ms(self, symbol: str) -> int | None:
        rows = self.storage.trades.list_recent(symbol=symbol, limit=1)
        return rows[0].ts_ms if rows else None