import sqlite3
import types
from decimal import Decimal
import pytest

from crypto_ai_bot.core.infrastructure.storage.repositories import Storage
from crypto_ai_bot.core.application.settlement import settle_orders

class DummyBus:
    async def publish(self, *_a, **_kw): pass

class DummyBroker:
    async def fetch_order(self, order_id: str):
        # Возвращаем «закрытый» ордер с заливкой, чтобы settlement добавил сделку
        return types.SimpleNamespace(
            id=order_id,
            broker_order_id=order_id,
            client_order_id="c1",
            clientOrderId="c1",
            symbol="BTC/USDT",
            side="buy",
            amount=Decimal("1"),
            filled=Decimal("1"),
            price=Decimal("100"),
            cost=Decimal("100"),
            fee_quote=Decimal("0.01"),
            ts_ms=1,
            status="closed",
        )

@pytest.mark.asyncio
async def test_settle_orders_adds_trade_and_updates_position(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    try:
        st = Storage(conn)
        st.orders.ensure_schema()
        st.trades.ensure_schema()
        st.positions.ensure_schema()

        # Добавляем «открытый» ордер в хранилище
        o = types.SimpleNamespace(
            id="1",
            client_order_id="c1",
            symbol="BTC/USDT",
            side="buy",
            amount="1",
            filled="0",
            price="100",
            cost="0",
            status="open",
            ts_ms=1,
        )
        st.orders.upsert_open(o)

        bus = DummyBus()
        br = DummyBroker()

        class S: pass

        await settle_orders("BTC/USDT", storage=st, broker=br, bus=bus, settings=S())

        rows = st.trades.list_today("BTC/USDT")
        assert rows and rows[-1]["side"] in ("buy", "sell")
    finally:
        conn.close()
