# tests/test_trades_repo.py
import sqlite3
from datetime import datetime, timezone

from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def test_fifo_pnl_and_window():
    con = sqlite3.connect(":memory:")
    repo = SqliteTradeRepository(con)

    # buy 1 @ 100
    repo.insert({
        "position_id": "p1", "symbol": "BTC/USDT", "side": "buy",
        "size": "1", "price": "100", "fee": None, "ts": iso_now(), "payload": None
    })
    # buy 1 @ 110 (avg 105)
    repo.insert({
        "position_id": "p1", "symbol": "BTC/USDT", "side": "buy",
        "size": "1", "price": "110", "fee": None, "ts": iso_now(), "payload": None
    })
    # sell 1 @ 120  → pnl = +15
    repo.insert({
        "position_id": "p1", "symbol": "BTC/USDT", "side": "sell",
        "size": "1", "price": "120", "fee": None, "ts": iso_now(), "payload": None
    })

    pnls = repo.last_closed_pnls(3)
    assert pnls, "should have at least one close"
    assert pnls[-1] > 0.0

    win = repo.get_realized_pnl(30)
    assert win > 0.0
