import types
from decimal import Decimal
from crypto_ai_bot.core.brokers import create_broker, ExchangeInterface

class _Cfg(types.SimpleNamespace):
    MODE: str = "paper"
    # добавь тут все поля, которые нужны реализациям .from_settings()

def test_factory_returns_interface():
    cfg = _Cfg(MODE="paper")
    broker = create_broker(cfg)
    assert isinstance(broker, ExchangeInterface)

def test_factory_modes():
    for mode in ("paper", "live", "backtest"):
        cfg = _Cfg(MODE=mode)
        b = create_broker(cfg)
        assert isinstance(b, ExchangeInterface)
        # smoke вызов обязательного метода
        assert hasattr(b, "fetch_ticker")
