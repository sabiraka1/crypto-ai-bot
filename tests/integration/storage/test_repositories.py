import pytest
from decimal import Decimal
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.storage.repositories.trades import TradesRepository
from crypto_ai_bot.core.infrastructure.storage.repositories.positions import PositionsRepository
from crypto_ai_bot.core.infrastructure.storage.repositories.idempotency import IdempotencyRepository
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.decimal import dec

def test_trades_repository(temp_db):
    """Тест репозитория сделок."""
    conn, _ = temp_db
    repo = TradesRepository(conn)
    
    # Добавляем сделку через order
    from crypto_ai_bot.core.infrastructure.brokers.base import OrderDTO
    order = OrderDTO(
        id="123",
        client_order_id="client-123",
        symbol="BTC/USDT",
        side="buy",
        amount=dec("0.001"),
        status="closed",
        filled=dec("0.001"),
        timestamp=now_ms(),
        price=dec("50000"),
        cost=dec("50")
    )
    
    trade_id = repo.add_from_order(order)
    assert trade_id is not None
    
    # Получаем последние сделки
    trades = repo.list_recent("BTC/USDT", limit=10)
    assert len(trades) == 1
    assert trades[0]["side"] == "buy"
    assert trades[0]["amount"] == "0.001"

def test_positions_repository(temp_db):
    """Тест репозитория позиций."""
    conn, _ = temp_db
    repo = PositionsRepository(conn)
    
    # Получаем пустую позицию
    pos = repo.get_position("BTC/USDT")
    assert pos.symbol == "BTC/USDT"
    assert pos.base_qty == dec("0")
    
    # Устанавливаем позицию
    repo.set_base_qty("BTC/USDT", dec("0.005"))
    
    # Проверяем
    pos = repo.get_position("BTC/USDT")
    assert pos.base_qty == dec("0.005")
    
    # Обновляем через trade
    trade = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": dec("0.002")
    }
    pos = repo.update_from_trade(trade)
    assert pos.base_qty == dec("0.007")

def test_idempotency_repository(temp_db):
    """Тест репозитория идемпотентности."""
    conn, _ = temp_db
    repo = IdempotencyRepository(conn)
    
    # Первая попытка должна пройти
    result = repo.check_and_store("key1", ttl_sec=60, default_bucket_ms=60000)
    assert result is True
    
    # Повторная попытка должна быть заблокирована
    result = repo.check_and_store("key1", ttl_sec=60, default_bucket_ms=60000)
    assert result is False
    
    # Другой ключ должен пройти
    result = repo.check_and_store("key2", ttl_sec=60, default_bucket_ms=60000)
    assert result is True
    
    # Очистка старых записей
    count = repo.prune_older_than(0)  # Удалить все
    assert count >= 2

def test_storage_facade(temp_db):
    """Тест фасада хранилища."""
    conn, _ = temp_db
    storage = Storage.from_connection(conn)
    
    assert storage.trades is not None
    assert storage.positions is not None
    assert storage.idempotency is not None
    assert storage.audit is not None
    assert storage.market_data is not None
    
    # Проверяем что методы работают
    pos = storage.positions.get_position("BTC/USDT")
    assert pos.base_qty == dec("0")