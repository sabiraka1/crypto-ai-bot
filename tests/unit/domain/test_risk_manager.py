from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager


def test_risk_config_from_settings(mock_settings):
    cfg = RiskConfig.from_settings(mock_settings)
    assert cfg.max_orders_per_hour == mock_settings.RISK_MAX_ORDERS_PER_HOUR


def test_risk_manager_allow_simple(mock_settings):
    rm = RiskManager(RiskConfig.from_settings(mock_settings))
    ok, reason = rm.allow(symbol="BTC/USDT", now_ms=0, storage=None)
    assert ok is True
    assert reason == "ok"
