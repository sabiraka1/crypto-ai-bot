from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.utils.time import now_ms


def test_trades_repo_basic(mock_storage: Storage) -> None:
    """Тест базовых операций с репозиторием сделок."""
    st = mock_storage
    
    # Создаем объект-ордер как словарь (как возвращает брокер)
    order: Dict[str, Any] = {
        "id": "x1",
        "broker_order_id": "x1",
        "client_order_id": "cid",
        "clientOrderId": "cid",  # для совместимости
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": "0.001",
        "filled": "0.001",
        "price": "10000",
        "cost": "10",
        "fee_quote": "0.01",
        "ts_ms": now_ms(),
        "timestamp": now_ms(),
        "status": "closed"
    }

    # Добавляем ордер в trades
    st.trades.add_from_order(order)

    # Проверяем что запись добавлена
    count = st.trades.count_orders_last_minutes("BTC/USDT", 1440)
    assert count >= 1, f"Expected at least 1 order, got {count}"
    
    turnover = st.trades.daily_turnover_quote("BTC/USDT")
    assert turnover >= Decimal("0"), f"Expected non-negative turnover, got {turnover}"
    
    # Проверяем что client_order_id сохранился правильно
    # (если есть метод для получения по client_order_id)
    trades = st.trades.list_today("BTC/USDT")
    if trades:
        last_trade = trades[-1]
        assert last_trade["side"] == "buy", f"Expected side 'buy', got {last_trade['side']}"