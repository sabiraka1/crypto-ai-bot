## `tests/unit/test_risk_manager.py`
from types import SimpleNamespace
from decimal import Decimal
from crypto_ai_bot.core.risk.manager import RiskManager, RiskConfig

def _ev(spread=0.05):
    # ✅ ИСПРАВЛЕНО: убрали features, spread_pct теперь напрямую в объекте
    return SimpleNamespace(spread_pct=spread)

def test_sell_without_position_blocked(container):
    rm = RiskManager(storage=container.storage)
    allowed, reason = container.storage.positions.get_base_qty(container.settings.SYMBOL), ""
    allowed, reason = awaitable(rm.check(symbol=container.settings.SYMBOL, action="sell", evaluation=_ev()))
    assert allowed is False and reason == "no_position"

def test_cooldown_and_spread(container):
    rm = RiskManager(storage=container.storage, config=RiskConfig(cooldown_sec=3600, max_spread_pct=0.01))
    # ✅ ТЕПЕРЬ РАБОТАЕТ: _ev(spread=1.0) создает SimpleNamespace(spread_pct=1.0)
    # RiskManager найдет spread_pct=1.0, сравнит с max_spread_pct=0.01
    # 1.0 > 0.01 = True → заблокирует с "spread_too_wide"
    allowed, reason = awaitable(rm.check(symbol=container.settings.SYMBOL, action="buy", evaluation=_ev(spread=1.0)))
    assert allowed is False and reason == "spread_too_wide"

import asyncio

def awaitable(coro):
    return asyncio.get_event_loop().run_until_complete(coro)