from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from crypto_ai_bot.utils.decimal import dec


@dataclass(frozen=True)
class RiskConfig:
    cooldown_sec: int = 0
    max_spread_pct: Decimal = dec("0.002")
    max_position_base: Decimal = dec("0")
    max_orders_per_hour: int = 0
    daily_loss_limit_quote: Decimal = dec("0")
    max_fee_pct: Decimal = dec("0.001")
    max_slippage_pct: Decimal = dec("0.001")


@dataclass(frozen=True)
class RiskInputs:
    spread_pct: Decimal
    position_base: Decimal
    recent_orders: int
    pnl_daily_quote: Decimal
    cooldown_active: bool
    # Дополнительные поля для расширенных проверок (опциональные)
    est_fee_pct: Optional[Decimal] = None
    est_slippage_pct: Optional[Decimal] = None


class RiskManager:
    """Упрощенный риск-менеджер с основными проверками."""

    def __init__(self, config: RiskConfig) -> None:
        self._cfg = config

    def check(self, inputs: RiskInputs | Dict[str, Any]) -> Dict[str, Any]:
        """Синхронная проверка рисков."""
        # Поддержка словаря для обратной совместимости
        if isinstance(inputs, dict):
            inputs = RiskInputs(
                spread_pct=dec(str(inputs.get('spread_pct', 0))),
                position_base=dec(str(inputs.get('position_base', 0))),
                recent_orders=inputs.get('recent_orders', inputs.get('orders_last_hour', 0)),
                pnl_daily_quote=dec(str(inputs.get('pnl_daily_quote', inputs.get('daily_pnl_quote', 0)))),
                cooldown_active=inputs.get('cooldown_active', False),
                est_fee_pct=dec(str(inputs.get('est_fee_pct', 0.001))) if 'est_fee_pct' in inputs else None,
                est_slippage_pct=dec(str(inputs.get('est_slippage_pct', 0.001))) if 'est_slippage_pct' in inputs else None,
            )

        reasons = []

        # Основные проверки
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

        # Дополнительные проверки если данные переданы
        if inputs.est_fee_pct and self._cfg.max_fee_pct and inputs.est_fee_pct > self._cfg.max_fee_pct:
            reasons.append("fee_too_high")
        
        if inputs.est_slippage_pct and self._cfg.max_slippage_pct and inputs.est_slippage_pct > self._cfg.max_slippage_pct:
            reasons.append("slippage_too_high")

        return {
            "ok": not reasons,
            "reasons": reasons,
            "deny_reasons": reasons,  # Для совместимости с eval_and_execute
            "limits": {
                "max_spread_pct": str(self._cfg.max_spread_pct),
                "max_fee_pct": str(self._cfg.max_fee_pct),
                "max_slippage_pct": str(self._cfg.max_slippage_pct),
                "max_position_base": str(self._cfg.max_position_base),
                "max_orders_per_hour": self._cfg.max_orders_per_hour,
                "daily_loss_limit_quote": str(self._cfg.daily_loss_limit_quote),
            },
        }

    def on_trade_executed(self, ts_ms: int) -> None:
        """Заглушка для совместимости."""
        pass