import sqlite3
import math
import pytest
from crypto_ai_bot.core.storage.repositories import trades as trades_repo

SqliteTradeRepository = trades_repo.SqliteTradeRepository

def test_create_and_get_trade():
    """Тест: создание pending-ордера и получение его по order_id."""
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)
    order_id = "TEST123"
    trade_id = repo.create_pending_order(symbol="BTC/USDT", side="buy", exp_price=50000.0, qty=0.1, order_id=order_id)
    assert isinstance(trade_id, int)
    trade = repo.get_by_order_id(order_id)
    assert trade is not None
    assert trade["order_id"] == order_id
    assert trade["symbol"] == "BTC/USDT"
    assert trade["side"] == "buy"
    # Начальное состояние должно быть 'pending'
    assert trade["state"] in ("pending", "partial")

def test_find_and_count_pending_orders():
    """Тест: поиск pending-ордеров и подсчет их количества."""
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)
    # Добавляем несколько pending ордеров
    repo.create_pending_order(symbol="BTC/USDT", side="buy", exp_price=100.0, qty=0.5, order_id="ORD1")
    repo.create_pending_order(symbol="ETH/USDT", side="buy", exp_price=2000.0, qty=1.0, order_id="ORD2")
    repo.create_pending_order(symbol="BTC/USDT", side="buy", exp_price=110.0, qty=0.2, order_id="ORD3")
    # Все pending-ордера
    pending_all = repo.find_pending_orders(symbol=None, limit=10)
    assert isinstance(pending_all, list)
    assert len(pending_all) == 3
    # Проверяем сортировку по времени (ts ASC)
    count = repo.count_pending()
    assert count == 3
    # Только ордера по BTC/USDT
    pending_btc = repo.find_pending_orders(symbol="BTC/USDT", limit=10)
    assert all(p["symbol"] == "BTC/USDT" for p in pending_btc)
    assert len(pending_btc) == 2

def test_list_by_symbol_and_order_insertion():
    """Тест: получение списка последних сделок по символу."""
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)
    # Добавляем несколько исполненных сделок
    repo.insert_trade(symbol="BTC/USDT", side="buy", price=100.0, qty=1.0, pnl=0.0)
    repo.insert_trade(symbol="BTC/USDT", side="sell", price=110.0, qty=1.0, pnl=10.0)
    repo.insert_trade(symbol="BTC/USDT", side="sell", price=105.0, qty=1.0, pnl=5.0)
    recent = repo.list_by_symbol("BTC/USDT", limit=2)
    assert len(recent) == 2
    # Должно быть отсортировано по ts DESC (новейшие сперва)
    assert recent[0]["id"] != recent[-1]["id"]
    assert all(tr["symbol"] == "BTC/USDT" for tr in recent)

def test_record_exchange_update_transitions():
    """Тест: обновление состояния ордера при получении статуса с биржи."""
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)
    order_id = "UPD123"
    # Создаем pending-запись
    repo.create_pending_order(symbol="XRP/USDT", side="buy", exp_price=1.0, qty=100.0, order_id=order_id)
    # Случай 1: частичное исполнение (partial fill)
    new_state1 = repo.record_exchange_update(order_id=order_id, exchange_status="partial", filled=50.0, average_price=1.05)
    assert new_state1 in ("partial", "pending")
    trade = repo.get_by_order_id(order_id)
    assert trade is not None
    assert math.isclose(trade["qty"], 50.0, rel_tol=1e-6)
    assert trade["state"] == new_state1
    # Случай 2: полное исполнение (filled)
    new_state2 = repo.record_exchange_update(order_id=order_id, exchange_status="closed", filled=100.0, average_price=1.02)
    assert new_state2 == "filled"
    trade2 = repo.get_by_order_id(order_id)
    assert trade2["state"] == "filled"
    assert math.isclose(trade2["qty"], 100.0, rel_tol=1e-6)
    # Случай 3: отмена ордера (canceled)
    order_id2 = "UPD124"
    repo.create_pending_order(symbol="XRP/USDT", side="buy", exp_price=2.0, qty=50.0, order_id=order_id2)
    new_state3 = repo.record_exchange_update(order_id=order_id2, exchange_status="canceled", filled=0.0, average_price=None)
    assert new_state3 == "canceled"
    trade3 = repo.get_by_order_id(order_id2)
    assert trade3["state"] == "canceled"
    # Случай 4: ордер не найден (создается запись и обновляется)
    missing_order = "UNKNOWN_ID"
    new_state4 = repo.record_exchange_update(order_id=missing_order, exchange_status="filled", filled=10.0, average_price=10.0)
    assert new_state4 == "filled"
    trade4 = repo.get_by_order_id(missing_order)
    assert trade4 is not None
    assert trade4["state"] == "filled"
    assert math.isclose(trade4["qty"], 10.0, rel_tol=1e-6)

def test_fill_cancel_reject_order():
    """Тест: методы fill_order, cancel_order, reject_order изменяют состояние правильно."""
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)
    order_id = "DIRECT1"
    repo.create_pending_order(symbol="LTC/USDT", side="buy", exp_price=50.0, qty=2.0, order_id=order_id)
    # fill_order
    repo.fill_order(order_id=order_id, executed_price=55.0, executed_qty=2.0, fee_amt=0.1, fee_ccy="USDT")
    trade = repo.get_by_order_id(order_id)
    assert trade["state"] == "filled"
    assert math.isclose(trade["price"], 55.0, rel_tol=1e-6)
    assert math.isclose(trade["qty"], 2.0, rel_tol=1e-6)
    # cancel_order
    order_id2 = "DIRECT2"
    repo.create_pending_order(symbol="LTC/USDT", side="buy", exp_price=60.0, qty=1.0, order_id=order_id2)
    repo.cancel_order(order_id=order_id2)
    trade2 = repo.get_by_order_id(order_id2)
    assert trade2["state"] == "canceled"
    # reject_order
    order_id3 = "DIRECT3"
    repo.create_pending_order(symbol="LTC/USDT", side="buy", exp_price=70.0, qty=1.0, order_id=order_id3)
    repo.reject_order(order_id=order_id3)
    trade3 = repo.get_by_order_id(order_id3)
    assert trade3["state"] == "rejected"

def test_realized_pnl_summary_profit():
    """Тест: PnL summary для прибыльной сделки."""
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)
    # Buy 1 @100, Sell 1 @110 (profit +10, +10%)
    repo.insert_trade(symbol="BTC/USDT", side="buy", price=100.0, qty=1.0, pnl=0.0)
    repo.insert_trade(symbol="BTC/USDT", side="sell", price=110.0, qty=1.0, pnl=0.0)
    summary = repo.realized_pnl_summary(symbol="BTC/USDT")
    assert summary["closed_trades"] == 1
    assert summary["wins"] == 1
    assert summary["losses"] == 0
    assert summary["pnl_abs"] == pytest.approx(10.0, rel=1e-6)
    assert summary["pnl_pct"] == pytest.approx(10.0, rel=1e-6)

def test_realized_pnl_summary_loss():
    """Тест: PnL summary для убыточной сделки."""
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)
    # Buy 1 @100, Sell 1 @90 (loss -10, -10%)
    repo.insert_trade(symbol="BTC/USDT", side="buy", price=100.0, qty=1.0, pnl=0.0)
    repo.insert_trade(symbol="BTC/USDT", side="sell", price=90.0, qty=1.0, pnl=0.0)
    summary = repo.realized_pnl_summary(symbol="BTC/USDT")
    assert summary["closed_trades"] == 1
    assert summary["wins"] == 0
    assert summary["losses"] == 1
    assert summary["pnl_abs"] == pytest.approx(-10.0, rel=1e-6)
    assert summary["pnl_pct"] == pytest.approx(-10.0, rel=1e-6)
