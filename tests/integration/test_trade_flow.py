import pytest
import asyncio
from decimal import Decimal
from unittest.mock import MagicMock
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.paper import PaperBroker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.utils.decimal import dec

@pytest.mark.asyncio
async def test_full_buy_sell_cycle(temp_db):
    """Тест полного цикла покупки и продажи."""
    conn, _ = temp_db
    storage = Storage.from_connection(conn)
    
    broker = PaperBroker(
        symbol="BTC/USDT",
        balances={"USDT": dec("1000"), "BTC": dec("0")},
        price_feed=lambda: dec("50000")
    )
    
    bus = AsyncEventBus()
    risk = RiskManager(RiskConfig())
    settings = MagicMock(FEE_PCT_ESTIMATE=dec("0.001"))
    
    # Покупка
    buy_result = await execute_trade(
        symbol="BTC/USDT",
        side="buy",
        storage=storage,
        broker=broker,
        bus=bus,
        exchange="gateio",
        quote_amount=dec("100"),
        idempotency_bucket_ms=60000,
        idempotency_ttl_sec=3600,
        risk_manager=risk,
        protective_exits=None,
        settings=settings
    )
    
    assert buy_result["executed"] is True
    assert buy_result["action"] == "buy"
    
    # Проверяем позицию
    pos = storage.positions.get_position("BTC/USDT")
    assert pos.base_qty > dec("0")
    
    # Продажа
    sell_result = await execute_trade(
        symbol="BTC/USDT",
        side="sell",
        storage=storage,
        broker=broker,
        bus=bus,
        exchange="gateio",
        base_amount=pos.base_qty,
        idempotency_bucket_ms=60000,
        idempotency_ttl_sec=3600,
        risk_manager=risk,
        protective_exits=None,
        settings=settings
    )
    
    assert sell_result["executed"] is True
    assert sell_result["action"] == "sell"
    
    # Проверяем что позиция закрыта
    pos_after = storage.positions.get_position("BTC/USDT")
    assert pos_after.base_qty == dec("0")
    
    # Проверяем баланс
    balance = await broker.fetch_balance("BTC/USDT")
    assert balance.free_base == dec("0")
    # Должно быть меньше 1000 из-за комиссий
    assert balance.free_quote < dec("1000")
    assert balance.free_quote > dec("990")  # Но не слишком мало