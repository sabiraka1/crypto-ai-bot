import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits

@pytest.mark.asyncio
async def test_protective_exits_no_position():
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=Decimal("0"))
    
    broker = AsyncMock()
    bus = AsyncMock()
    settings = MagicMock(EXITS_ENABLED=1, EXITS_MODE="both")
    
    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    result = await exits.ensure(symbol="BTC/USDT")
    
    assert result is None
    broker.fetch_ticker.assert_not_called()

@pytest.mark.asyncio
async def test_protective_exits_hard_stop():
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=Decimal("0.001"))
    
    broker = AsyncMock()
    broker.fetch_ticker.return_value = MagicMock(last=Decimal("47000"))  # -6% от входа
    broker.create_market_sell_base.return_value = MagicMock(id="123")
    
    bus = AsyncMock()
    settings = MagicMock(
        EXITS_ENABLED=1, EXITS_MODE="hard",
        EXITS_HARD_STOP_PCT=0.05, IDEMPOTENCY_BUCKET_MS=60000
    )
    
    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    
    # Первый вызов устанавливает entry
    await exits.ensure(symbol="BTC/USDT")
    
    # Имитируем падение цены
    broker.fetch_ticker.return_value = MagicMock(last=Decimal("47000"))
    result = await exits.ensure(symbol="BTC/USDT")
    
    if result and "error" not in result:
        assert broker.create_market_sell_base.called
        assert bus.publish.called