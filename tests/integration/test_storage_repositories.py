from decimal import Decimal


def test_trades_repo_basic(mock_storage):
    st = mock_storage
    # Добавляем ордер (как PaperBroker возвращает объект с полями)
    order = type("O", (), {})()
    order.id = "x1"; order.client_order_id = "cid"; order.symbol = "BTC/USDT"
    order.side = "buy"; order.amount = Decimal("0.001"); order.price = Decimal("10000")
    order.cost = order.amount * order.price; order.fee_quote = Decimal("0"); order.ts_ms = 0

    st.trades.add_from_order(order)

    assert st.trades.count_orders_last_minutes("BTC/USDT", 1440) >= 1
    assert st.trades.daily_turnover_quote("BTC/USDT") >= 0
