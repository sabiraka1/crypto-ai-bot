import pytest
from decimal import Decimal

from crypto_ai_bot.core.brokers.ccxt_exchange import CcxtExchange
from crypto_ai_bot.core.brokers.base import TickerDTO

class _FakeClient:
    def __init__(self):
        self._m = {
            "BTC/USDT": {
                "precision": {"amount": 6, "price": 2},
                "limits": {"amount": {"min": 0.0001}, "cost": {"min": 5}},
            }
        }

    def load_markets(self):
        return self._m

    def market(self, symbol):
        return self._m[symbol]

    def fetch_ticker(self, symbol):
        return {"last": 50000.0, "bid": 49999.0, "ask": 50001.0, "timestamp": 0}

    def create_order(self, symbol, type_, side, amount, price=None, params=None):
        # просто возвращаем эхо, проверка суммы происходит на уровне брокера
        return {"id": "x", "amount": amount, "status": "closed"}

@pytest.mark.anyio
async def test_buy_quote_amount_rounding(monkeypatch):
    # подменяем реальный ccxt-клиент внутри объекта
    ex = CcxtExchange(exchange="gateio")
    fake = _FakeClient()
    ex._client = fake  # type: ignore

    od = await ex.create_market_buy_quote("BTC/USDT", 100.0, client_order_id="cid-1")
    # ask=50001 → base≈0.00199996 → округление вниз до 6 знаков = 0.001999
    assert od.side == "buy" and pytest.approx(od.amount, rel=1e-9) == 0.001999

@pytest.mark.anyio
async def test_sell_base_amount_rounding(monkeypatch):
    ex = CcxtExchange(exchange="gateio")
    fake = _FakeClient()
    ex._client = fake  # type: ignore

    od = await ex.create_market_sell_base("BTC/USDT", 0.001234567, client_order_id="cid-2")
    # amount precision 6 → 0.001234
    assert od.side == "sell" and pytest.approx(od.amount, rel=1e-9) == 0.001234

@pytest.mark.anyio
async def test_min_limits(monkeypatch):
    ex = CcxtExchange(exchange="gateio")
    fake = _FakeClient()
    ex._client = fake  # type: ignore

    # cost min = 5 USDT, amount min = 0.0001 BTC
    with pytest.raises(Exception):
        await ex.create_market_buy_quote("BTC/USDT", 1.0)
    with pytest.raises(Exception):
        await ex.create_market_sell_base("BTC/USDT", 0.00001)