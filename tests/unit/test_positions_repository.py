import sqlite3
from crypto_ai_bot.core.storage.repositories import trades as trades_repo, positions as positions_repo

SqliteTradeRepository = trades_repo.SqliteTradeRepository
SqlitePositionRepository = positions_repo.SqlitePositionRepository

def test_get_open_and_has_long_qty():
    """Тест: начальное состояние позиций и функции has_long/long_qty."""
    con = sqlite3.connect(":memory:")
    pos_repo = SqlitePositionRepository(con)
    # Изначально позиций нет
    open_positions = pos_repo.get_open()
    assert open_positions == []
    # has_long возвращает False, long_qty == 0.0
    assert pos_repo.has_long("BTC/USDT") is False
    assert pos_repo.long_qty("BTC/USDT") == 0.0

def test_recompute_positions_partial_and_close():
    """Тест: пересчет позиций из трейдов (частичное и полное закрытие)."""
    con = sqlite3.connect(":memory:")
    trade_repo = SqliteTradeRepository(con)
    pos_repo = SqlitePositionRepository(con)
    symbol = "ADA/USDT"
    # Добавляем сделки: покупка 1 @10, покупка 1 @14, продажа 1 @12
    trade_repo.insert_trade(symbol=symbol, side="buy", price=10.0, qty=1.0, pnl=0.0)
    trade_repo.insert_trade(symbol=symbol, side="buy", price=14.0, qty=1.0, pnl=0.0)
    trade_repo.insert_trade(symbol=symbol, side="sell", price=12.0, qty=1.0, pnl=0.0)
    pos_repo.recompute_from_trades(symbol=symbol)
    open_positions = pos_repo.get_open()
    # Должна остаться одна открытая позиция
    assert len(open_positions) == 1
    pos = open_positions[0]
    assert pos["symbol"] == symbol
    assert pos["qty"] == 1.0  # 1 ADA остался
    # Средняя цена ~14 или ~12 (в зависимости от FIFO-логики)
    assert abs(pos["avg_price"] - 14.0) < 1e-6 or abs(pos["avg_price"] - 12.0) < 1e-6
    # long_qty и has_long должны отражать оставшуюся позицию
    assert pos_repo.has_long(symbol) is True
    assert pos_repo.long_qty(symbol) == 1.0
    # Добавляем еще одну продажу 1 @15 (полное закрытие)
    trade_repo.insert_trade(symbol=symbol, side="sell", price=15.0, qty=1.0, pnl=0.0)
    pos_repo.recompute_from_trades(symbol=symbol)
    open_positions_after = pos_repo.get_open()
    # Все позиции должны быть закрыты
    assert open_positions_after == []
    assert pos_repo.has_long(symbol) is False
    assert pos_repo.long_qty(symbol) == 0.0
