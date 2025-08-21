## `tests/unit/test_risk_manager.py`
from types import SimpleNamespace
from decimal import Decimal
from crypto_ai_bot.core.risk.manager import RiskManager, RiskConfig
def _ev(spread=0.05):
    return SimpleNamespace(features={"spread_pct": spread})
def test_sell_without_position_blocked(container):
    rm = RiskManager(storage=container.storage)
    allowed, reason = container.storage.positions.get_base_qty(container.settings.SYMBOL), ""
    allowed, reason = awaitable(rm.check(symbol=container.settings.SYMBOL, action="sell", evaluation=_ev()))
    assert allowed is False and reason == "no_position"
def test_cooldown_and_spread(container):
    rm = RiskManager(storage=container.storage, config=RiskConfig(cooldown_sec=3600, max_spread_pct=0.01))
    allowed, reason = awaitable(rm.check(symbol=container.settings.SYMBOL, action="buy", evaluation=_ev(spread=1.0)))
    assert allowed is False and reason == "spread_too_wide"
import asyncio
def awaitable(coro):
    return asyncio.get_event_loop().run_until_complete(coro)