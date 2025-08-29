import pytest
from decimal import Decimal
from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakRule
from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownRule
from crypto_ai_bot.utils.decimal import dec

def test_loss_streak_rule():
    """Тест правила серии убытков."""
    rule = LossStreakRule(max_streak=3, lookback_trades=10)
    
    # Пустая история - разрешено
    allowed, reason = rule.check([])
    assert allowed is True
    
    # Серия убыточных продаж
    trades = [
        {"side": "sell", "cost": "-10"},
        {"side": "sell", "cost": "-20"},
        {"side": "sell", "cost": "-15"}
    ]
    
    allowed, reason = rule.check(trades)
    assert allowed is False  # 3 убытка подряд
    assert "loss_streak" in reason
    
    # С прибыльной сделкой в конце
    trades.append({"side": "sell", "cost": "50"})
    allowed, reason = rule.check(trades)
    assert allowed is True  # Серия прервана

def test_max_drawdown_rule():
    """Тест правила максимальной просадки."""
    rule = MaxDrawdownRule(
        max_drawdown_pct=dec("10"),
        max_daily_loss_quote=dec("100")
    )
    
    # Проверка дневного лимита
    allowed, reason = rule.check(
        current_balance=dec("900"),
        peak_balance=dec("1000"),
        daily_pnl=dec("-150")  # Превышает лимит
    )
    assert allowed is False
    assert "daily_loss_exceeded" in reason
    
    # Проверка общей просадки
    allowed, reason = rule.check(
        current_balance=dec("850"),
        peak_balance=dec("1000"),
        daily_pnl=dec("-50")
    )
    assert allowed is False  # 15% просадка > 10% лимит
    assert "max_drawdown" in reason
    
    # Нормальная ситуация
    allowed, reason = rule.check(
        current_balance=dec("950"),
        peak_balance=dec("1000"),
        daily_pnl=dec("-30")
    )
    assert allowed is True
    assert reason == "ok"

def test_drawdown_calculation():
    """Тест расчета метрик просадки."""
    rule = MaxDrawdownRule()
    
    balances = [
        dec("1000"),
        dec("1100"),  # Peak
        dec("1050"),
        dec("900"),   # Trough
        dec("950")
    ]
    
    metrics = rule.calculate_drawdown(balances)
    
    assert metrics["peak"] == dec("1100")
    assert metrics["max"] > dec("15")  # ~18% от 1100 до 900
    
    # Recovery ratio
    recovery = rule.recovery_ratio(
        current=dec("950"),
        trough=dec("900"),
        peak=dec("1100")
    )
    assert recovery == dec("25")  # 25% восстановления от 900 к 1100