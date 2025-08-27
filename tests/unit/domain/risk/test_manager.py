from decimal import Decimal
import pytest
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig, RiskInputs
from crypto_ai_bot.utils.time import now_ms

@pytest.fixture
def risk_config():
    return RiskConfig(
        cooldown_sec=60,
        max_spread_pct=Decimal("0.5"),
        max_position_base=Decimal("0.1"),
        max_orders_per_hour=10,
        daily_loss_limit_quote=Decimal("100")
    )

def test_risk_manager_cooldown(risk_config):
    rm = RiskManager(risk_config)
    now = now_ms()
    
    # Первая сделка разрешена
    inputs = RiskInputs(
        now_ms=now, action="BUY_QUOTE", spread_pct=Decimal("0.1"),
        position_base=Decimal("0"), orders_last_hour=0,
        daily_pnl_quote=Decimal("0"), est_fee_pct=Decimal("0.001"),
        est_slippage_pct=Decimal("0.001")
    )
    result = rm.check(inputs)
    assert result["ok"] is True
    
    # Отметим выполнение
    rm.on_trade_executed(now)
    
    # Вторая сразу после - блокирована cooldown
    inputs2 = RiskInputs(
        now_ms=now + 30000,  # +30 секунд
        action="BUY_QUOTE", spread_pct=Decimal("0.1"),
        position_base=Decimal("0"), orders_last_hour=1,
        daily_pnl_quote=Decimal("0"), est_fee_pct=Decimal("0.001"),
        est_slippage_pct=Decimal("0.001")
    )
    result2 = rm.check(inputs2)
    assert result2["ok"] is False
    assert "cooldown" in result2["reasons"]

def test_risk_manager_spread_limit(risk_config):
    rm = RiskManager(risk_config)
    
    inputs = RiskInputs(
        now_ms=now_ms(), action="BUY_QUOTE",
        spread_pct=Decimal("1.0"),  # Превышает лимит 0.5%
        position_base=Decimal("0"), orders_last_hour=0,
        daily_pnl_quote=Decimal("0"), est_fee_pct=Decimal("0.001"),
        est_slippage_pct=Decimal("0.001")
    )
    result = rm.check(inputs)
    assert result["ok"] is False
    assert "spread_too_wide" in result["reasons"]

def test_risk_manager_legacy_interface(risk_config):
    rm = RiskManager(risk_config)
    
    # Старый интерфейс из спецификации
    result = rm.check("BTC/USDT", "buy", {"spread_pct": 0.1})
    assert result["ok"] is True
    assert "limits" in result