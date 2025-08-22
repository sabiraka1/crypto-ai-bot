import pytest
from decimal import Decimal
from crypto_ai_bot.core.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.utils.time import now_ms

def _insert_trade(conn, *, symbol: str, side: str, amount: float, price: float, cost: float, status: str = 'closed', ts_ms: int = None):
    ts = ts_ms or now_ms()
    conn.execute(
        """
        INSERT INTO trades (broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, created_at_ms)
        VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"cid-{ts}-{side}", symbol, side, amount, price, cost, status, ts, ts),
    )
    conn.commit()

@pytest.mark.anyio
async def test_position_cap_blocks_buy(container):
    sym = container.settings.SYMBOL
    # создадим позицию 0.01 BTC
    _insert_trade(container.storage.conn, symbol=sym, side='buy', amount=0.01, price=100.0, cost=1.0)

    rm = RiskManager(storage=container.storage, config=RiskConfig(max_position_base=Decimal('0.005')))
    allowed, reason = await rm.check(symbol=sym, action='buy', evaluation={})
    assert allowed is False and reason == 'position_cap_exceeded'

@pytest.mark.anyio
async def test_orders_throttle(container):
    sym = container.settings.SYMBOL
    rm = RiskManager(storage=container.storage, config=RiskConfig(max_orders_per_hour=2))

    # зарегистрируем 2 ордера
    rm.on_order_placed(symbol=sym)
    rm.on_order_placed(symbol=sym)

    allowed, reason = await rm.check(symbol=sym, action='buy', evaluation={})
    assert allowed is False and reason == 'orders_limit_reached'

@pytest.mark.anyio
async def test_daily_loss_limit_blocks_after_loss(container):
    sym = container.settings.SYMBOL

    # round-trip с убытком: купили на 100, продали на 80 (позиция плоская)
    _insert_trade(container.storage.conn, symbol=sym, side='buy', amount=0.002, price=50000.0, cost=100.0)
    _insert_trade(container.storage.conn, symbol=sym, side='sell', amount=0.002, price=40000.0, cost=80.0)

    rm = RiskManager(storage=container.storage, config=RiskConfig(daily_loss_limit_quote=Decimal('10')))
    allowed, reason = await rm.check(symbol=sym, action='buy', evaluation={})
    assert allowed is False and reason == 'daily_loss_limit_reached'
