import sqlite3
import types
from decimal import Decimal
from math import isclose

import pytest

from crypto_ai_bot.core.infrastructure.storage.repositories import Storage
from crypto_ai_bot.utils.time import now_ms

@pytest.mark.parametrize("fee_buy, fee_sell", [
    (Decimal("0.10"), Decimal("0.10")),
    (Decimal("0.00"), Decimal("0.05")),
])
def test_pnl_and_turnover_today(tmp_path, fee_buy, fee_sell):
    """
    Моделируем две сделки за 'сегодня': покупка и продажа 1 BTC по 100 и 110.
    Проверяем, что PnL_today > 0 с учётом комиссий, а оборот равен сумме cost.
    """
    conn = sqlite3.connect(tmp_path / "pnl.db")
    try:
        st = Storage(conn)
        st.trades.ensure_schema()

        ts = now_ms()

        # Покупка: 1 @ 100
        buy_order = types.SimpleNamespace(
            id="o1",
            broker_order_id="o1",
            client_order_id="c1",
            clientOrderId="c1",
            symbol="BTC/USDT",
            side="buy",
            amount=Decimal("1"),
            filled=Decimal("1"),
            price=Decimal("100"),
            cost=Decimal("100"),
            fee_quote=fee_buy,
            ts_ms=ts,
            timestamp=ts,
            status="closed",
        )
        st.trades.add_from_order(buy_order)

        # Продажа: 1 @ 110
        sell_order = types.SimpleNamespace(
            id="o2",
            broker_order_id="o2",
            client_order_id="c2",
            clientOrderId="c2",
            symbol="BTC/USDT",
            side="sell",
            amount=Decimal("1"),
            filled=Decimal("1"),
            price=Decimal("110"),
            cost=Decimal("110"),
            fee_quote=fee_sell,
            ts_ms=ts + 1000,
            timestamp=ts + 1000,
            status="closed",
        )
        st.trades.add_from_order(sell_order)

        pnl = st.trades.pnl_today_quote("BTC/USDT")
        turnover = st.trades.daily_turnover_quote("BTC/USDT")

        # Оборот — сумма котируемой стоимости сделок
        assert turnover == Decimal("210")

        # Ожидаемая прибыль = 110 - 100 - fee_buy - fee_sell
        expected = Decimal("10") - (fee_buy + fee_sell)
        # Допускаем микроскопическую погрешность округления
        assert isclose(float(pnl), float(expected), rel_tol=1e-9, abs_tol=1e-9)
        assert pnl > Decimal("0")
    finally:
        conn.close()
