import pytest
from decimal import Decimal
from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CcxtBroker
from crypto_ai_bot.core.infrastructure.brokers.paper import PaperBroker
from crypto_ai_bot.utils.decimal import dec

@pytest.mark.asyncio
async def test_broker_interface_paper():
    """Тест интерфейса PaperBroker."""
    broker = PaperBroker(
        symbol="BTC/USDT",
        balances={"USDT": dec("1000"), "BTC": dec("0")},
        price_feed=lambda: dec("50000")  # ✅ Добавлен price_feed
    )
    
    # Тест ticker
    ticker = await broker.fetch_ticker("BTC/USDT")
    assert ticker.last > 0
    assert ticker.bid > 0
    assert ticker.ask > 0
    assert ticker.bid < ticker.last < ticker.ask
    
    # Тест баланса
    balance = await broker.fetch_balance("BTC/USDT")
    assert balance.free_quote == dec("1000")
    assert balance.free_base == dec("0")
    
    # Тест покупки
    order = await broker.create_market_buy_quote(
        symbol="BTC/USDT",
        quote_amount=dec("100"),
        client_order_id="test-buy-1"
    )
    assert order.side == "buy"
    assert order.status == "closed"
    assert order.filled > 0
    
    # Проверяем изменение баланса
    balance_after = await broker.fetch_balance("BTC/USDT")
    assert balance_after.free_quote < dec("1000")
    assert balance_after.free_base > dec("0")

@pytest.mark.asyncio
async def test_broker_interface_paper_sell():
    """Тест продажи через PaperBroker."""
    broker = PaperBroker(
        symbol="BTC/USDT",
        balances={"USDT": dec("0"), "BTC": dec("0.001")},
        price_feed=lambda: dec("50000")
    )
    
    # Тест продажи
    order = await broker.create_market_sell_base(
        symbol="BTC/USDT",
        base_amount=dec("0.001"),
        client_order_id="test-sell-1"
    )
    assert order.side == "sell"
    assert order.status == "closed"
    assert order.filled == dec("0.001")
    
    # Проверяем баланс после продажи
    balance = await broker.fetch_balance("BTC/USDT")
    assert balance.free_base == dec("0")
    assert balance.free_quote > dec("0")

@pytest.mark.asyncio
async def test_ccxt_dry_run():
    """Тест CcxtBroker в dry_run режиме."""
    broker = CcxtBroker(
        exchange_id="gateio",
        api_key="",
        api_secret="",
        dry_run=True
    )
    
    ticker = await broker.fetch_ticker("BTC/USDT")
    assert ticker.last == dec("100")
    
    balance = await broker.fetch_balance("BTC/USDT")
    assert balance.free_quote == dec("100000")
    assert balance.free_base == dec("0")
    
    # Тест dry_run ордера
    order = await broker.create_market_buy_quote(
        symbol="BTC/USDT",
        quote_amount=dec("50"),
        client_order_id="dry-test-1"
    )
    assert order.id.startswith("dry-")
    assert order.status == "closed"