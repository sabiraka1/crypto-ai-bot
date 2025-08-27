from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .rules.loss_streak import LossStreakRule
from .rules.max_drawdown import MaxDrawdownRule
from crypto_ai_bot.utils.decimal import dec


@dataclass(frozen=True)
class RiskConfig:
    cooldown_sec: int
    max_spread_pct: Decimal
    max_position_base: Decimal
    max_orders_per_hour: int
    daily_loss_limit_quote: Decimal
    # доп. пороги
    max_fee_pct: Decimal = dec("0.001")
    max_slippage_pct: Decimal = dec("0.001")
    # правила для loss streak и drawdown
    max_loss_streak: int = 3
    max_drawdown_pct: Decimal = dec("10.0")


@dataclass(frozen=True)
class RiskInputs:
    now_ms: int
    action: str                  # "BUY_QUOTE" | "SELL_BASE"
    spread_pct: Decimal
    position_base: Decimal
    orders_last_hour: int
    daily_pnl_quote: Decimal
    est_fee_pct: Decimal
    est_slippage_pct: Decimal
    # дополнительно для правил
    recent_trades: Optional[List[Dict[str, Any]]] = None
    current_balance: Optional[Decimal] = None
    peak_balance: Optional[Decimal] = None


class RiskManager:
    """Чистый домен: никаких импортов инфраструктуры, всё приходит во входах."""

    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self._last_trade_ms: int = 0
        
        # Инициализируем правила
        self._loss_streak = LossStreakRule(
            max_streak=config.max_loss_streak,
            lookback_trades=10
        )
        self._drawdown = MaxDrawdownRule(
            max_drawdown_pct=config.max_drawdown_pct,
            max_daily_loss_quote=config.daily_loss_limit_quote
        )

    def check(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Поддержка двух интерфейсов:
        1. check(inputs: RiskInputs) - новый
        2. check(symbol, action, evaluation) - из спецификации
        """
        # Если передан RiskInputs
        if len(args) == 1 and isinstance(args[0], RiskInputs):
            return self._check_inputs(args[0])
        
        # Если передан словарь напрямую (упрощенный вариант для eval_and_execute)
        if len(args) == 1 and isinstance(args[0], dict):
            # Конвертируем словарь в RiskInputs
            from crypto_ai_bot.utils.time import now_ms
            d = args[0]
            inputs = RiskInputs(
                now_ms=d.get('now_ms', now_ms()),
                action=d.get('action', 'BUY_QUOTE'),
                spread_pct=dec(str(d.get('spread_pct', 0))),
                position_base=dec(str(d.get('position_base', 0))),
                orders_last_hour=d.get('recent_orders', d.get('orders_last_hour', 0)),
                daily_pnl_quote=dec(str(d.get('pnl_daily_quote', d.get('daily_pnl_quote', 0)))),
                est_fee_pct=dec(str(d.get('est_fee_pct', 0.001))),
                est_slippage_pct=dec(str(d.get('est_slippage_pct', 0.001))),
                recent_trades=d.get('recent_trades'),
                current_balance=dec(str(d.get('current_balance', 0))) if d.get('current_balance') else None,
                peak_balance=dec(str(d.get('peak_balance', 0))) if d.get('peak_balance') else None,
            )
            return self._check_inputs(inputs)
        
        # Старый интерфейс из спецификации (symbol, action, evaluation)
        if len(args) >= 2 or ('symbol' in kwargs and 'action' in kwargs):
            symbol = args[0] if args else kwargs.get('symbol')
            action = args[1] if len(args) > 1 else kwargs.get('action')
            evaluation = args[2] if len(args) > 2 else kwargs.get('evaluation', {})
            
            # Конвертируем в RiskInputs
            from crypto_ai_bot.utils.time import now_ms
            inputs = RiskInputs(
                now_ms=evaluation.get('now_ms', now_ms()),
                action="BUY_QUOTE" if action == "buy" else "SELL_BASE" if action == "sell" else action,
                spread_pct=dec(str(evaluation.get('spread_pct', 0))),
                position_base=dec(str(evaluation.get('position_base', 0))),
                orders_last_hour=evaluation.get('orders_last_hour', 0),
                daily_pnl_quote=dec(str(evaluation.get('daily_pnl_quote', 0))),
                est_fee_pct=dec(str(evaluation.get('est_fee_pct', 0.001))),
                est_slippage_pct=dec(str(evaluation.get('est_slippage_pct', 0.001))),
                recent_trades=evaluation.get('recent_trades'),
                current_balance=dec(str(evaluation.get('current_balance', 0))) if evaluation.get('current_balance') else None,
                peak_balance=dec(str(evaluation.get('peak_balance', 0))) if evaluation.get('peak_balance') else None,
            )
            return self._check_inputs(inputs)
        
        # Если ничего не подходит - пустой разрешающий ответ для совместимости
        return {"ok": True, "reasons": [], "limits": {}}

    def _check_inputs(self, inputs: RiskInputs) -> Dict[str, Any]:
        """Основная логика проверки."""
        reasons: List[str] = []

        # Существующие проверки
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

        # Проверка серии убытков
        if inputs.recent_trades and inputs.action == "BUY_QUOTE":
            streak_ok, streak_reason = self._loss_streak.check(inputs.recent_trades)
            if not streak_ok:
                reasons.append(streak_reason)

        # Проверка просадки
        if inputs.current_balance and inputs.peak_balance:
            dd_ok, dd_reason = self._drawdown.check(
                inputs.current_balance,
                inputs.peak_balance,
                inputs.daily_pnl_quote
            )
            if not dd_ok:
                reasons.append(dd_reason)

        return {
            "ok": not reasons,
            "reasons": reasons,
            "deny_reasons": reasons,  # Для совместимости с eval_and_execute
            "limits": {
                "max_spread_pct": str(self.config.max_spread_pct),
                "max_fee_pct": str(self.config.max_fee_pct),
                "max_slippage_pct": str(self.config.max_slippage_pct),
                "max_position_base": str(self.config.max_position_base),
                "max_orders_per_hour": self.config.max_orders_per_hour,
                "daily_loss_limit_quote": str(self.config.daily_loss_limit_quote),
                "max_loss_streak": self.config.max_loss_streak,
                "max_drawdown_pct": str(self.config.max_drawdown_pct),
            },
        }

    def on_trade_executed(self, ts_ms: int) -> None:
        self._last_trade_ms = ts_ms