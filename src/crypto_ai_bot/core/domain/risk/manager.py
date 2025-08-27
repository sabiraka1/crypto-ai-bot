from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List


@dataclass(frozen=True)
class RiskConfig:
    cooldown_sec: int
    max_spread_pct: Decimal
    max_position_base: Decimal
    max_orders_per_hour: int
    daily_loss_limit_quote: Decimal
    # доп. пороги
    max_fee_pct: Decimal = Decimal("0.001")
    max_slippage_pct: Decimal = Decimal("0.001")


@dataclass(frozen=True)
class RiskInputs:
    now_ms: int
    action: str                     # "BUY_QUOTE" | "SELL_BASE"
    spread_pct: Decimal
    position_base: Decimal
    orders_last_hour: int
    daily_pnl_quote: Decimal
    est_fee_pct: Decimal
    est_slippage_pct: Decimal


class RiskManager:
    """Чистая доменная модель. Никаких импортов infra; всё приходит входными данными."""

    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self._last_trade_ms: int = 0

    def check(self, inputs: RiskInputs) -> Dict[str, Any]:
        reasons: List[str] = []

        if self._last_trade_ms and (inputs.now_ms - self._last_trade_ms) < self.config.cooldown_sec * 1000:
            reasons.append("cooldown")
        if inputs.spread_pct > self.config.max_spread_pct:
            reasons.append("spread_too_wide")
        if inputs.action == "BUY_QUOTE" and inputs.position_base >= self.config.max_position_base:
            reasons.append("position_limit")
        if inputs.orders_last_hour >= self.config.max_orders_per_hour:
            reasons.append("rate_limit")
        if inputs.daily_pnl_quote < -self.config.daily_loss_limit_quote:
            reasons.append("daily_loss_limit")
        if inputs.est_fee_pct > self.config.max_fee_pct:
            reasons.append("fee_too_high")
        if inputs.est_slippage_pct > self.config.max_slippage_pct:
            reasons.append("slippage_too_high")

        ok = not reasons
        return {
            "ok": ok,
            "reasons": reasons,
            "limits": {
                "max_spread_pct": str(self.config.max_spread_pct),
                "max_fee_pct": str(self.config.max_fee_pct),
                "max_slippage_pct": str(self.config.max_slippage_pct),
                "max_position_base": str(self.config.max_position_base),
                "max_orders_per_hour": self.config.max_orders_per_hour,
                "daily_loss_limit_quote": str(self.config.daily_loss_limit_quote),
            },
        }

    def on_trade_executed(self, ts_ms: int) -> None:
        self._last_trade_ms = ts_ms
