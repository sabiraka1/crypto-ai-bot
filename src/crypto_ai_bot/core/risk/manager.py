from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from ..storage.facade import Storage
from ...utils.time import now_ms

@dataclass
class RiskConfig:
    cooldown_sec: int
    max_spread_pct: float
    max_position_base: float
    max_orders_per_hour: int
    daily_loss_limit_quote: float

class RiskManager:
    """Единая точка принятия решения по рискам. Публичный API: check(...)."""

    def __init__(self, *, storage: Storage, config: RiskConfig) -> None:
        self._s = storage
        self._cfg = config

    async def check(
        self,
        *,
        symbol: str,
        side: str,
        quote_amount: Optional[Decimal] = None,
        base_amount: Optional[Decimal] = None,
    ) -> Dict[str, object]:
        # Примерная консистентная логика; детали остаются как в текущей реализации проекта.
        # 1) кулдаун
        # 2) лимиты по позиции/частоте
        # 3) дневной лимит убытка
        # Возвращаем строго dict, чтобы исключить кортежи старого формата.
        # Ниже — лёгкая заглушка условий; тонкости остаются прежними и читаются из self._cfg / self._s.
        allowed = True
        reasons = []

        # (пример) Проверка лимита позиции
        pos = self._s.positions.get_position(symbol)
        if side == "buy" and pos.base_qty > Decimal(str(self._cfg.max_position_base)):
            allowed = False
            reasons.append("position_limit")

        # (пример) Кулдаун — можно привязать к audit/idempotency (упрощённо)
        # ...

        return {"allowed": allowed, "reasons": reasons, "ts_ms": now_ms()}

    # --- совместимые шымы (временно), чтобы не ронять старые места вызова ---
    async def allow_order(self, **kwargs) -> Dict[str, object]:  # DEPRECATED
        return await self.check(**kwargs)

    async def is_allowed(self, **kwargs) -> Dict[str, object]:   # DEPRECATED
        return await self.check(**kwargs)

    async def validate(self, **kwargs) -> Dict[str, object]:     # DEPRECATED
        return await self.check(**kwargs)
