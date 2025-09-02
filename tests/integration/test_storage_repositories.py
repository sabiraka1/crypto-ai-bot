from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.utils.time import now_ms


def test_trades_repo_basic(mock_storage: Storage) -> None:
    """Тест базовых операций с репозиторием сделок."""
    st = mock_storage
    
    # Создаем объект-ордер (как ожидает add_from_order)
    class Order:
        def __init__(self) -> None:
            self.id = "x1"
            self.broker_order_id = "x1"
            self.client_order_id = "cid"
            self.symbol = "BTC/USDT"
            self.side = "buy"
            self.amount = Decimal("0.001")
            self.filled = Decimal("0.001")
            self.price = Decimal("10000")
            self.cost = Decimal("10")
            self.fee_quote = Decimal("0.01")
            self.ts_ms = now_ms()
            self.timestamp = now_ms()
            self.status = "closed"
    
    order = Order()

    # Добавляем ордер в trades
    st.trades.add_from_order(order)

    # Проверяем что запись добавлена
    count = st.trades.count_orders_last_minutes("BTC/USDT", 1440)
    assert count >= 1, f"Expected at least 1 order, got {count}"
    
    turnover = st.trades.daily_turnover_quote("BTC/USDT")
    assert turnover >= Decimal("0"), f"Expected non-negative turnover, got {turnover}"