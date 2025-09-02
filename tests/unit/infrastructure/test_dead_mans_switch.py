import pytest
from unittest.mock import AsyncMock
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch

@pytest.mark.asyncio
async def test_trigger_awaits_broker_call():
    broker = type("B", (), {})()
    broker.create_market_sell_base = AsyncMock()
    dms = DeadMansSwitch(broker)
    await dms.trigger("BTC/USDT", 0.01)
    broker.create_market_sell_base.assert_awaited()
