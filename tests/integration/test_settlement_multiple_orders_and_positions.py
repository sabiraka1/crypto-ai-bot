import sqlite3
import types
from decimal import Decimal

import pytest

from crypto_ai_bot.core.infrastructure.storage.repositories import Storage
from crypto_ai_bot.core.application.settlement import settle_orders

class DummyBus:
    async def publish(self, *_a, **_kw): pass

class DummyBroker:
    def __init__(self):
        self._orders = {}

    def plan_closed_order(self, order_id: str, side: str, price: Decimal):
        self._orders[order_id] = types.SimpleNamespace(
            id=order_id,
            broker_order_id=order_id,
            client_order_id=order_id,
            clientOrderId=order_id,
            symbol="BTC/USDT",
            side=side,
            amount=Decimal("1"),
            filled=Decimal("1"),
            price=price,
            cost=price,
            fee_quote=Decimal("0.00"),
            ts_ms=1,
            status="closed",
        )

    async def fetch_order(self, order_id: str):
        return self._orders[order_id]

@pytest.mark.asyncio
async def test_settlement_buy_then_sell_updates_positions_and_trades(tmp_path):
    """
    Два закрытых ордера: BUY@100, SELL@110.
    Проверяем:
      - после первого settle → позиция base_qty = 1, сделок = 1
      - после второго settle → позиция base_qty = 0, сделок = 2
    """
    conn = sqlite3.connect(tmp_path / "settle2.db")
    try:
        st = Storage(conn)
        st.orders.ensure_schema()
        st.trades.ensure_schema()
        st.positions.ensure_schema()

        # Готовим два 'open' ордера в БД
        o1 = types.SimpleNamespace(
            id="1", client_order_id="1", symbol="BTC/USDT", side="buy",
            amount="1", filled="0", price="100", cost="0", status="open", ts_ms=1,
        )
        o2 = types.SimpleNamespace(
            id="2", client_order_id="2", symbol="BTC/USDT", side="sell",
            amount="1", filled="0", price="110", cost="0", status="open", ts_ms=2,
        )
        st.orders.upsert_open(o1)
        st.orders.upsert_open(o2)

        # Брокер 'закрывает' оба ордера
        br = DummyBroker()
        br.plan_closed_order("1", "buy", Decimal("100"))
        br.plan_closed_order("2", "sell", Decimal("110"))

        bus = DummyBus()

        class S: pass

        # Первый settle — купили 1
        await settle_orders("BTC/USDT", storage=st, broker=br, bus=bus, settings=S())
        trades = st.trades.list_today("BTC/USDT")
        pos1 = st.positions.get_position("BTC/USDT")
        assert trades and len(trades) == 1
        assert Decimal(str(pos1["base_qty"])) == Decimal("1")

        # Второй settle — продали 1
        await settle_orders("BTC/USDT", storage=st, broker=br, bus=bus, settings=S())
        trades2 = st.trades.list_today("BTC/USDT")
        pos2 = st.positions.get_position("BTC/USDT")
        assert len(trades2) == 2
        assert Decimal(str(pos2["base_qty"])) == Decimal("0")
    finally:
        conn.close()
