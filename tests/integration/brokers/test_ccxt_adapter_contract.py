import pytest
from decimal import Decimal
from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CcxtBroker
from crypto_ai_bot.core.infrastructure.brokers.paper import PaperBroker

@pytest.mark.asyncio
async def test_broker_interface_paper():
    broker = PaperBroker(
        symbol="BTC/USDT",
        balances={"USDT": Decimal("1000"), "BTC": Decimal("0")}
    )
    
    # Тест ticker
    ticker = await broker.fetch_ticker("BTC/USDT")
    assert ticker.last > 0
    assert ticker.bid > 0
    assert ticker.ask > 0
    
    # Тест баланса
    balance = await broker.fetch_balance("BTC/USDT")
    assert balance.free_quote == Decimal("1000")
    assert balance.free_base == Decimal("0")
    
    # Тест покупки
    order = await broker.create_market_buy_quote(
        symbol="BTC/USDT",
        quote_amount=Decimal("100"),
        client_order_id="test-buy-1"
    )
    assert order.side == "buy"
    assert order.status == "closed"
    assert order.filled > 0

@pytest.mark.asyncio
async def test_ccxt_dry_run():
    broker = CcxtBroker(
        exchange_id="gateio",
        api_key="",
        api_secret="",
        dry_run=True
    )
    
    ticker = await broker.fetch_ticker("BTC/USDT")
    assert ticker.last == Decimal("100")
    
    balance = await broker.fetch_balance("BTC/USDT")
    assert balance.free_quote == Decimal("100000")