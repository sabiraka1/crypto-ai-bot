import pytest

from crypto_ai_bot.core.application.protective_exits import ProtectiveExits


@pytest.mark.asyncio
async def test_exits_evaluate_noop(mock_storage, mock_broker, mock_settings):
    exits = ProtectiveExits(storage=mock_storage, broker=mock_broker, bus=None, settings=mock_settings)
    res = await exits.evaluate(symbol="BTC/USDT")
    assert res is None
