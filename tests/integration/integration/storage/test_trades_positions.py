import pytest
from crypto_ai_bot.core.infrastructure.storage.sqlite_adapter import SQLiteAdapter
from crypto_ai_bot.core.infrastructure.storage.repositories.trades import TradesRepository
from crypto_ai_bot.core.infrastructure.storage.repositories.positions import PositionsRepository

@pytest.fixture
def db():
    return SQLiteAdapter(path=":memory:")

def test_trades_schema_and_insert_list_today(db):
    tr = TradesRepository(db)
    tr.ensure_schema()
    oid = tr.add_from_order({"symbol":"BTC/USDT","side":"buy","amount":"0.01","price":"50000","fee_quote":"0.5","clientOrderId":"c-1"})
    rows = tr.list_today("BTC/USDT")
    assert rows and rows[-1]["client_order_id"] == "c-1"

def test_positions_schema(db):
    pr = PositionsRepository(db)
    pr.ensure_schema()
    # just ensure no exceptions
