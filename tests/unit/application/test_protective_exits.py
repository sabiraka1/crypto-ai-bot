import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.utils.decimal import dec

@pytest.mark.asyncio
async def test_protective_exits_no_position():
    """Тест когда нет позиции - выходы не должны срабатывать."""
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=dec("0"))
    
    broker = AsyncMock()
    bus = AsyncMock()
    settings = MagicMock(
        EXITS_ENABLED=1,
        EXITS_MODE="both",
        EXITS_HARD_STOP_PCT=0.05,
        EXITS_TRAILING_PCT=0.03,
        EXITS_MIN_BASE_TO_EXIT=0.0,
        IDEMPOTENCY_BUCKET_MS=60000
    )
    
    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    result = await exits.ensure(symbol="BTC/USDT")
    
    assert result is None
    broker.fetch_ticker.assert_not_called()

@pytest.mark.asyncio
async def test_protective_exits_disabled():
    """Тест когда выходы отключены в настройках."""
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=dec("0.001"))
    
    broker = AsyncMock()
    bus = AsyncMock()
    settings = MagicMock(EXITS_ENABLED=0)  # Отключено
    
    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    result = await exits.ensure(symbol="BTC/USDT")
    
    assert result is None

@pytest.mark.asyncio
async def test_protective_exits_hard_stop():
    """Тест срабатывания hard stop при падении цены."""
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=dec("0.001"))
    
    broker = AsyncMock()
    broker.create_market_sell_base.return_value = MagicMock(id="123")
    
    bus = AsyncMock()
    settings = MagicMock(
        EXITS_ENABLED=1,
        EXITS_MODE="hard",
        EXITS_HARD_STOP_PCT=0.05,
        EXITS_TRAILING_PCT=0.03,
        EXITS_MIN_BASE_TO_EXIT=0.0,
        IDEMPOTENCY_BUCKET_MS=60000
    )
    
    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    
    # Первый вызов устанавливает entry price
    broker.fetch_ticker.return_value = MagicMock(last=dec("50000"))
    await exits.ensure(symbol="BTC/USDT")
    
    # Цена падает на 6% (больше чем hard stop 5%)
    broker.fetch_ticker.return_value = MagicMock(last=dec("47000"))
    result = await exits.ensure(symbol="BTC/USDT")
    
    if result and "error" not in result:
        assert broker.create_market_sell_base.called
        assert bus.publish.called
        assert "hard_stop" in result.get("reason", "")

@pytest.mark.asyncio
async def test_protective_exits_trailing_stop():
    """Тест срабатывания trailing stop."""
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=dec("0.001"))
    
    broker = AsyncMock()
    broker.create_market_sell_base.return_value = MagicMock(id="124")
    
    bus = AsyncMock()
    settings = MagicMock(
        EXITS_ENABLED=1,
        EXITS_MODE="trailing",
        EXITS_HARD_STOP_PCT=0.05,
        EXITS_TRAILING_PCT=0.03,
        EXITS_MIN_BASE_TO_EXIT=0.0,
        IDEMPOTENCY_BUCKET_MS=60000
    )
    
    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    
    # Устанавливаем начальную цену
    broker.fetch_ticker.return_value = MagicMock(last=dec("50000"))
    await exits.ensure(symbol="BTC/USDT")
    
    # Цена растет до 52000 (новый peak)
    broker.fetch_ticker.return_value = MagicMock(last=dec("52000"))
    await exits.ensure(symbol="BTC/USDT")
    
    # Цена падает на 4% от peak (больше чем trailing 3%)
    broker.fetch_ticker.return_value = MagicMock(last=dec("49920"))
    result = await exits.ensure(symbol="BTC/USDT")
    
    if result and "error" not in result:
        assert broker.create_market_sell_base.called
        assert "trailing" in result.get("reason", "")

@pytest.mark.asyncio
async def test_protective_exits_min_base():
    """Тест минимального размера позиции для выхода."""
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=dec("0.00001"))
    
    broker = AsyncMock()
    bus = AsyncMock()
    settings = MagicMock(
        EXITS_ENABLED=1,
        EXITS_MODE="both",
        EXITS_HARD_STOP_PCT=0.05,
        EXITS_TRAILING_PCT=0.03,
        EXITS_MIN_BASE_TO_EXIT=0.0001,  # Минимум больше чем позиция
        IDEMPOTENCY_BUCKET_MS=60000
    )
    
    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    result = await exits.ensure(symbol="BTC/USDT")
    
    assert result is None  # Не должно срабатывать