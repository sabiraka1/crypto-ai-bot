from decimal import Decimal
import pytest
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig, RiskInputs
from crypto_ai_bot.utils.decimal import dec

@pytest.fixture
def risk_config():
    return RiskConfig(
        cooldown_sec=60,
        max_spread_pct=dec("0.5"),
        max_position_base=dec("0.1"),
        max_orders_per_hour=10,
        daily_loss_limit_quote=dec("100"),
        max_fee_pct=dec("0.001"),
        max_slippage_pct=dec("0.001")
    )

def test_risk_manager_all_ok(risk_config):
    """Тест когда все проверки проходят."""
    rm = RiskManager(risk_config)
    
    inputs = RiskInputs(
        spread_pct=dec("0.1"),
        position_base=dec("0.05"),
        recent_orders=5,
        pnl_daily_quote=dec("50"),
        cooldown_active=False,
        est_fee_pct=dec("0.0005"),
        est_slippage_pct=dec("0.0005")
    )
    
    result = rm.check(inputs)
    assert result["ok"] is True
    assert result["reasons"] == []
    assert "limits" in result

def test_risk_manager_cooldown_active(risk_config):
    """Тест блокировки по cooldown."""
    rm = RiskManager(risk_config)
    
    inputs = RiskInputs(
        spread_pct=dec("0.1"),
        position_base=dec("0"),
        recent_orders=0,
        pnl_daily_quote=dec("0"),
        cooldown_active=True  # Активен cooldown
    )
    
    result = rm.check(inputs)
    assert result["ok"] is False
    assert "cooldown_active" in result["reasons"]

def test_risk_manager_spread_too_wide(risk_config):
    """Тест блокировки по широкому спреду."""
    rm = RiskManager(risk_config)
    
    inputs = RiskInputs(
        spread_pct=dec("1.0"),  # Превышает лимит 0.5%
        position_base=dec("0"),
        recent_orders=0,
        pnl_daily_quote=dec("0"),
        cooldown_active=False
    )
    
    result = rm.check(inputs)
    assert result["ok"] is False
    assert "spread_too_wide" in result["reasons"]

def test_risk_manager_position_limit(risk_config):
    """Тест блокировки по размеру позиции."""
    rm = RiskManager(risk_config)
    
    inputs = RiskInputs(
        spread_pct=dec("0.1"),
        position_base=dec("0.2"),  # Превышает лимит 0.1
        recent_orders=0,
        pnl_daily_quote=dec("0"),
        cooldown_active=False
    )
    
    result = rm.check(inputs)
    assert result["ok"] is False
    assert "position_limit_exceeded" in result["reasons"]

def test_risk_manager_rate_limit(risk_config):
    """Тест блокировки по количеству ордеров."""
    rm = RiskManager(risk_config)
    
    inputs = RiskInputs(
        spread_pct=dec("0.1"),
        position_base=dec("0"),
        recent_orders=15,  # Превышает лимит 10
        pnl_daily_quote=dec("0"),
        cooldown_active=False
    )
    
    result = rm.check(inputs)
    assert result["ok"] is False
    assert "orders_rate_limit" in result["reasons"]

def test_risk_manager_daily_loss_limit(risk_config):
    """Тест блокировки по дневному убытку."""
    rm = RiskManager(risk_config)
    
    inputs = RiskInputs(
        spread_pct=dec("0.1"),
        position_base=dec("0"),
        recent_orders=0,
        pnl_daily_quote=dec("-150"),  # Превышает лимит -100
        cooldown_active=False
    )
    
    result = rm.check(inputs)
    assert result["ok"] is False
    assert "daily_loss_limit_reached" in result["reasons"]

def test_risk_manager_dict_compatibility(risk_config):
    """Тест совместимости со старым интерфейсом через dict."""
    rm = RiskManager(risk_config)
    
    # Старый интерфейс через словарь
    result = rm.check({
        "spread_pct": 0.1,
        "position_base": 0.05,
        "recent_orders": 5,
        "pnl_daily_quote": 50,
        "cooldown_active": False
    })
    
    assert result["ok"] is True