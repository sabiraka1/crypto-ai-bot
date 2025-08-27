from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any


@dataclass(frozen=True)
class RiskConfig:
    cooldown_sec: int = 0
    max_spread_pct: Decimal = Decimal("0.002")  # 0.2%
    max_position_base: Decimal = Decimal("0")   # 0 = без лимита
    max_orders_per_hour: int = 0               # 0 = без лимита
    daily_loss_limit_quote: Decimal = Decimal("0")  # 0 = без лимита


@dataclass(frozen=True)
class RiskInputs:
    spread_pct: Decimal
    position_base: Decimal
    recent_orders: int
    pnl_daily_quote: Decimal
    cooldown_active: bool


class RiskManager:
    """Чистый domain-класс: без импортов из infrastructure/application."""

    def __init__(self, config: RiskConfig) -> None:
        self._cfg = config

    async def check(self, inputs: RiskInputs) -> Dict[str, Any]:
        reasons = []

        if self._cfg.cooldown_sec > 0 and inputs.cooldown_active:
            reasons.append("cooldown_active")

        if self._cfg.max_spread_pct and inputs.spread_pct > self._cfg.max_spread_pct:
            reasons.append("spread_too_wide")

        if self._cfg.max_position_base and inputs.position_base > self._cfg.max_position_base:
            reasons.append("position_limit_exceeded")

        if self._cfg.max_orders_per_hour and inputs.recent_orders >= self._cfg.max_orders_per_hour:
            reasons.append("orders_rate_limit")

        if self._cfg.daily_loss_limit_quote and inputs.pnl_daily_quote <= -abs(self._cfg.daily_loss_limit_quote):
            reasons.append("daily_loss_limit_reached")

        return {"ok": not reasons, "deny_reasons": reasons}
