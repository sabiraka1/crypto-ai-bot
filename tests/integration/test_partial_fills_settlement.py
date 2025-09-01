import sqlite3
import pytest
from types import SimpleNamespace

from crypto_ai_bot.core.infrastructure.storage.repositories.orders import OrdersRepository
from crypto_ai_bot.core.infrastructure.storage.repositories.trades import TradesRepository
from crypto_ai_bot.core.infrastructure.storage.repositories.positions import PositionsRepository
from crypto_ai_bot.core.application.use_cases.partial_fills import settle_orders


class DummyBus:
    def __init__(self):
        self.events = []

    async def publish(self, name, payload):
        self.events.append((name, payload))


class DummyBroker:
    def __init__(self):
        self.queried = []

    async def fetch_order(self, symbol, broker_order_id):
        self.queried.append((symbol, broker_order_id))
        # simulate fully filled order
        return SimpleNamespace(
            status="closed",
            filled="1",
            amount="1",
            side="buy",
            price="100",
            fee_quote="0",
            ts_ms=2,
        )


class Storage:
    def __init__(self, conn):
        self.orders = OrdersRepository(conn)
        self.trades = TradesRepository(conn)
        self.positions = PositionsRepository(conn)


@pytest.mark.asyncio
async def test_settle_orders_adds_trade_and_updates_position(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    st = Storage(conn)
    st.orders.ensure_schema()
    st.trades.ensure_schema()
    st.positions.ensure_schema()

    class OpenOrder:
        pass

    o = OpenOrder()
    o.id = "1"
    o.client_order_id = "c1"
    o.symbol = "BTC/USDT"
    o.side = "buy"
    o.amount = "1"
    o.filled = "0"
    o.status = "open"
    o.ts_ms = 1

    st.orders.upsert_open(o)

    bus = DummyBus()
    br = DummyBroker()

    class S:
        pass

    await settle_orders("BTC/USDT", storage=st, broker=br, bus=bus, settings=S())

    rows = st.trades.list_today("BTC/USDT")
    assert rows and rows[-1]["side"] in ("buy", "sell")

    pos = st.positions.get_position("BTC/USDT")
    assert pos and pos.base_qty > 0
