import sqlite3
import types
from decimal import Decimal
from math import isclose
import time

import pytest

from crypto_ai_bot.core.infrastructure.storage.repositories import Storage

def ms_now():
    return int(time.time() * 1000)

def ms_days_ago(days: int) -> int:
    return ms_now() - days * 24 * 60 * 60 * 1000

@pytest.mark.parametrize("fee_btc, fee_eth", [
    (Decimal("0.10"), Decimal("0.05")),
    (Decimal("0.00"), Decimal("0.00")),
])
def test_pnl_and_turnover_today_multi_symbol_and_cutoff(tmp_path, fee_btc, fee_eth):
    """
    Сегодня: BTC buy@100 → sell@110 (1.0), с комиссиями.
    Вчера:   ETH buy@10 → sell@11 (2.0), не должен попадать в today's PnL/turnover.
    Проверяем, что BTC-метрики верны, а ETH-метрики за сегодня равны 0.
    """
    conn = sqlite3.connect(tmp_path / "pnl_multi.db")
    try:
        st = Storage(conn)
        st.trades.ensure_schema()

        # ---- Сегодня: BTC сделки
        ts_today_1 = ms_now()
        ts_today_2 = ts_today_1 + 1000

        btc_buy = types.SimpleNamespace(
            id="b1", broker_order_id="b1", client_order_id="b1", clientOrderId="b1",
            symbol="BTC/USDT", side="buy",
            amount=Decimal("1.0"), filled=Decimal("1.0"),
            price=Decimal("100"), cost=Decimal("100"),
            fee_quote=fee_btc, ts_ms=ts_today_1, timestamp=ts_today_1,
            status="closed",
        )
        st.trades.add_from_order(btc_buy)

        btc_sell = types.SimpleNamespace(
            id="s1", broker_order_id="s1", client_order_id="s1", clientOrderId="s1",
            symbol="BTC/USDT", side="sell",
            amount=Decimal("1.0"), filled=Decimal("1.0"),
            price=Decimal("110"), cost=Decimal("110"),
            fee_quote=fee_btc, ts_ms=ts_today_2, timestamp=ts_today_2,
            status="closed",
        )
        st.trades.add_from_order(btc_sell)

        # ---- Вчера: ETH сделки (не должны попасть в today's)
        ts_yest_1 = ms_days_ago(1)
        ts_yest_2 = ts_yest_1 + 1000

        eth_buy = types.SimpleNamespace(
            id="b2", broker_order_id="b2", client_order_id="b2", clientOrderId="b2",
            symbol="ETH/USDT", side="buy",
            amount=Decimal("2.0"), filled=Decimal("2.0"),
            price=Decimal("10"), cost=Decimal("20"),
            fee_quote=fee_eth, ts_ms=ts_yest_1, timestamp=ts_yest_1,
            status="closed",
        )
        st.trades.add_from_order(eth_buy)

        eth_sell = types.SimpleNamespace(
            id="s2", broker_order_id="s2", client_order_id="s2", clientOrderId="s2",
            symbol="ETH/USDT", side="sell",
            amount=Decimal("2.0"), filled=Decimal("2.0"),
            price=Decimal("11"), cost=Decimal("22"),
            fee_quote=fee_eth, ts_ms=ts_yest_2, timestamp=ts_yest_2,
            status="closed",
        )
        st.trades.add_from_order(eth_sell)

        # ---- Проверки
        btc_pnl = st.trades.pnl_today_quote("BTC/USDT")
        btc_turnover = st.trades.daily_turnover_quote("BTC/USDT")
        # оборот BTC за сегодня = 100 + 110
        assert btc_turnover == Decimal("210")

        expected_btc = Decimal("10") - (fee_btc + fee_btc)
        assert isclose(float(btc_pnl), float(expected_btc), rel_tol=1e-9, abs_tol=1e-9)
        assert btc_pnl >= Decimal("0")

        eth_pnl_today = st.trades.pnl_today_quote("ETH/USDT")
        eth_turnover_today = st.trades.daily_turnover_quote("ETH/USDT")
        assert eth_pnl_today == Decimal("0")
        assert eth_turnover_today == Decimal("0")
    finally:
        conn.close()
