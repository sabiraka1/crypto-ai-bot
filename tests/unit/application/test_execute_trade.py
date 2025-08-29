import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.utils.decimal import dec

@pytest.mark.asyncio
async def test_execute_trade_buy_success(mock_storage, mock_broker):
    """Тест успешной покупки."""
    bus = AsyncMock()
    risk_manager = RiskManager(RiskConfig())
    protective_exits = AsyncMock()
    settings = MagicMock(FEE_PCT_ESTIMATE=dec("0.001"))
    
    # Настраиваем storage
    mock_storage.positions.get_position.return_value = MagicMock(base_qty=dec("0"))
    mock_storage.idempotency.check_and_store.return_value = True
    
    result = await execute_trade(
        symbol="BTC/USDT",
        side="buy",
        storage=mock_storage,
        broker=mock_broker,
        bus=bus,
        exchange="gateio",
        quote_amount=dec("100"),
        idempotency_bucket_ms=60000,
        idempotency_ttl_sec=3600,
        risk_manager=risk_manager,
        protective_exits=protective_exits,
        settings=settings
    )
    
    assert result["action"] == "buy"
    assert result["executed"] is True
    assert "order" in result
    mock_broker.create_market_buy_quote.assert_called_once()
    bus.publish.assert_called()

@pytest.mark.asyncio
async def test_execute_trade_sell_success(mock_storage, mock_broker):
    """Тест успешной продажи."""
    bus = AsyncMock()
    risk_manager = RiskManager(RiskConfig())
    protective_exits = AsyncMock()
    settings = MagicMock(FEE_PCT_ESTIMATE=dec("0.001"))
    
    # Настраиваем storage с позицией
    mock_storage.positions.get_position.return_value = MagicMock(base_qty=dec("0.001"))
    
    result = await execute_trade(
        symbol="BTC/USDT",
        side="sell",
        storage=mock_storage,
        broker=mock_broker,
        bus=bus,
        exchange="gateio",
        base_amount=dec("0.001"),
        idempotency_bucket_ms=60000,
        idempotency_ttl_sec=3600,
        risk_manager=risk_manager,
        protective_exits=protective_exits,
        settings=settings
    )
    
    assert result["action"] == "sell"
    assert result["executed"] is True
    mock_broker.create_market_sell_base.assert_called_once()

@pytest.mark.asyncio
async def test_execute_trade_risk_blocked(mock_storage, mock_broker):
    """Тест блокировки риск-менеджером."""
    bus = AsyncMock()
    
    # Настраиваем риск-менеджер для блокировки
    risk_config = RiskConfig(max_spread_pct=dec("0.01"))  # Очень низкий лимит
    risk_manager = RiskManager(risk_config)
    
    protective_exits = AsyncMock()
    settings = MagicMock(FEE_PCT_ESTIMATE=dec("0.001"))
    
    # Настраиваем высокий спред
    mock_broker.fetch_ticker.return_value = MagicMock(
        last=dec("50000"),
        bid=dec("49000"),  # Большой спред
        ask=dec("51000"),
        timestamp=1700000000000
    )
    
    result = await execute_trade(
        symbol="BTC/USDT",
        side="buy",
        storage=mock_storage,
        broker=mock_broker,
        bus=bus,
        exchange="gateio",
        quote_amount=dec("100"),
        idempotency_bucket_ms=60000,
        idempotency_ttl_sec=3600,
        risk_manager=risk_manager,
        protective_exits=protective_exits,
        settings=settings
    )
    
    assert result["action"] == "skip"
    assert result["executed"] is False
    assert "blocked" in result.get("why", "")
    mock_broker.create_market_buy_quote.assert_not_called()

@pytest.mark.asyncio
async def test_execute_trade_idempotency_duplicate(mock_storage, mock_broker):
    """Тест идемпотентности - дубликат."""
    bus = AsyncMock()
    risk_manager = None  # Без риск-менеджера
    protective_exits = AsyncMock()
    settings = MagicMock(FEE_PCT_ESTIMATE=dec("0.001"))
    
    # Настраиваем идемпотентность для отклонения
    mock_storage.idempotency.check_and_store.return_value = False
    
    result = await execute_trade(
        symbol="BTC/USDT",
        side="buy",
        storage=mock_storage,
        broker=mock_broker,
        bus=bus,
        exchange="gateio",
        quote_amount=dec("100"),
        idempotency_bucket_ms=60000,
        idempotency_ttl_sec=3600,
        risk_manager=risk_manager,
        protective_exits=protective_exits,
        settings=settings
    )
    
    assert result["action"] == "skip"
    assert result["executed"] is False
    assert result.get("reason") == "duplicate"
    mock_broker.create_market_buy_quote.assert_not_called()