"""
Loss streak risk rule.
Блокирует торговлю при серии убыточных сделок.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from crypto_ai_bot.core.domain.risk.policies import (
    CriticalRiskRule,
    RiskAction,
    RiskContext,
    RiskResult,
    RiskSeverity,
)
from crypto_ai_bot.utils.decimal import dec


class LossStreakRule(CriticalRiskRule):
    """
    Правило серии убытков.
    
    Блокирует торговлю при достижении лимита подряд идущих убыточных сделок.
    Это критическое правило - при срабатывании полностью останавливает торговлю.
    """
    
    def __init__(
        self,
        max_streak: int = 3,
        name: str = "loss_streak",
        enabled: bool = True
    ):
        """
        Args:
            max_streak: Максимальное количество убыточных сделок подряд
            name: Имя правила
            enabled: Включено ли правило
        """
        super().__init__(name=name, enabled=enabled)
        self.max_streak = max_streak
    
    async def check(self, context: RiskContext) -> RiskResult:
        """
        Проверить серию убытков.
        
        Args:
            context: Контекст с информацией о текущей серии убытков
            
        Returns:
            RiskResult с действием BLOCK если серия превышена
        """
        if not self.enabled or self.max_streak <= 0:
            return RiskResult(
                action=RiskAction.ALLOW,
                rule_name=self.name,
                severity=RiskSeverity.INFO,
                reason="Rule disabled",
                metadata={"enabled": False}
            )
        
        current_streak = context.loss_streak
        
        # Проверяем превышение лимита
        if current_streak >= self.max_streak:
            return RiskResult(
                action=RiskAction.BLOCK,
                rule_name=self.name,
                severity=RiskSeverity.CRITICAL,
                reason=f"Loss streak limit exceeded: {current_streak} >= {self.max_streak}",
                score=dec("100"),  # Максимальный риск
                threshold=dec(str(self.max_streak)),
                current_value=dec(str(current_streak)),
                metadata={
                    "current_streak": current_streak,
                    "max_streak": self.max_streak,
                    "symbol": context.symbol,
                    "action_required": "Reset trading or wait for profitable trade"
                }
            )
        
        # Предупреждение при приближении к лимиту
        if current_streak == self.max_streak - 1:
            return RiskResult(
                action=RiskAction.WARNING,
                rule_name=self.name,
                severity=RiskSeverity.HIGH,
                reason=f"Approaching loss streak limit: {current_streak}/{self.max_streak}",
                score=dec("75"),  # Высокий риск
                threshold=dec(str(self.max_streak)),
                current_value=dec(str(current_streak)),
                metadata={
                    "current_streak": current_streak,
                    "max_streak": self.max_streak,
                    "trades_until_block": 1
                }
            )
        
        # Нормальное состояние
        risk_score = dec(str(current_streak)) / dec(str(self.max_streak)) * 100 if self.max_streak > 0 else dec("0")
        
        return RiskResult(
            action=RiskAction.ALLOW,
            rule_name=self.name,
            severity=RiskSeverity.INFO,
            reason=f"Loss streak within limits: {current_streak}/{self.max_streak}",
            score=risk_score,
            threshold=dec(str(self.max_streak)),
            current_value=dec(str(current_streak)),
            metadata={
                "current_streak": current_streak,
                "max_streak": self.max_streak,
                "trades_until_block": self.max_streak - current_streak
            }
        )


class AdvancedLossStreakRule(LossStreakRule):
    """
    Расширенное правило серии убытков с учетом размера убытков.
    
    Учитывает не только количество, но и суммарный размер убытков в серии.
    """
    
    def __init__(
        self,
        max_streak: int = 3,
        max_streak_loss_quote: Optional[Decimal] = None,
        reduction_per_loss: Decimal = dec("0.25"),  # Уменьшать на 25% за каждый убыток
        name: str = "advanced_loss_streak",
        enabled: bool = True
    ):
        """
        Args:
            max_streak: Максимальное количество убыточных сделок подряд
            max_streak_loss_quote: Максимальный суммарный убыток в серии (в quote валюте)
            reduction_per_loss: На сколько уменьшать позицию за каждый убыток в серии
            name: Имя правила
            enabled: Включено ли правило
        """
        super().__init__(max_streak=max_streak, name=name, enabled=enabled)
        self.max_streak_loss_quote = max_streak_loss_quote
        self.reduction_per_loss = reduction_per_loss
    
    async def check(self, context: RiskContext) -> RiskResult:
        """
        Проверить серию убытков с учетом их размера.
        
        Может не только блокировать, но и уменьшать размер позиции
        при накоплении убытков.
        """
        # Базовая проверка количества
        base_result = await super().check(context)
        
        # Если уже заблокировано - возвращаем как есть
        if base_result.action == RiskAction.BLOCK:
            return base_result
        
        current_streak = context.loss_streak
        
        # Проверка суммарного убытка в серии (если задан лимит)
        if self.max_streak_loss_quote and context.daily_pnl < 0:
            streak_loss = abs(context.daily_pnl)  # Примерная оценка через daily PnL
            
            if streak_loss >= self.max_streak_loss_quote:
                return RiskResult(
                    action=RiskAction.BLOCK,
                    rule_name=self.name,
                    severity=RiskSeverity.CRITICAL,
                    reason=f"Streak loss limit exceeded: {streak_loss} >= {self.max_streak_loss_quote}",
                    score=dec("100"),
                    threshold=self.max_streak_loss_quote,
                    current_value=streak_loss,
                    metadata={
                        "current_streak": current_streak,
                        "streak_loss": float(streak_loss),
                        "max_loss": float(self.max_streak_loss_quote),
                        "action_required": "Stop trading until reset"
                    }
                )
        
        # Уменьшение позиции при наличии убытков в серии
        if current_streak > 0 and current_streak < self.max_streak:
            reduction_factor = dec("1") - (self.reduction_per_loss * dec(str(current_streak)))
            reduction_factor = max(dec("0.1"), reduction_factor)  # Минимум 10% от исходного размера
            
            suggested_amount = context.amount * reduction_factor
            
            return RiskResult(
                action=RiskAction.REDUCE,
                rule_name=self.name,
                severity=RiskSeverity.MEDIUM,
                reason=f"Reducing position due to loss streak: {current_streak}",
                suggested_amount=suggested_amount,
                reduction_factor=reduction_factor,
                score=dec(str(50 + current_streak * 15)),  # Прогрессивный скоринг
                threshold=dec(str(self.max_streak)),
                current_value=dec(str(current_streak)),
                metadata={
                    "current_streak": current_streak,
                    "reduction_pct": str((dec("1") - reduction_factor) * 100),
                    "original_amount": str(context.amount),
                    "suggested_amount": str(suggested_amount)
                }
            )
        
        return base_result


# Фабричные функции для создания правил

def create_loss_streak_rule(max_streak: int = 3) -> LossStreakRule:
    """Создать базовое правило серии убытков"""
    return LossStreakRule(max_streak=max_streak)


def create_advanced_loss_streak_rule(
    max_streak: int = 3,
    max_loss: Optional[Decimal] = None,
    reduction: Decimal = dec("0.25")
) -> AdvancedLossStreakRule:
    """Создать расширенное правило с учетом размера убытков"""
    return AdvancedLossStreakRule(
        max_streak=max_streak,
        max_streak_loss_quote=max_loss,
        reduction_per_loss=reduction
    )


__all__ = [
    "LossStreakRule",
    "AdvancedLossStreakRule", 
    "create_loss_streak_rule",
    "create_advanced_loss_streak_rule",
]