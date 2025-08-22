import pytest
from crypto_ai_bot.core.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.utils.metrics import snapshot

@pytest.mark.anyio
async def test_risk_block_counters_increment(container):
    sym = container.settings.SYMBOL
    rm = RiskManager(storage=container.storage, config=RiskConfig(max_spread_pct=0.01))

    # заведомо широкий спред, чтобы сработал блок по spread
    allowed, reason = await rm.check(symbol=sym, action="buy", evaluation={"spread": 1.0})
    assert allowed is False and reason == "spread_too_wide"

    snap = snapshot()
    series = snap["counters"].get("risk_blocked_total", [])
    got = [x for x in series if x["labels"].get("reason") == "spread_too_wide"]
    assert got and got[0]["value"] >= 1.0
