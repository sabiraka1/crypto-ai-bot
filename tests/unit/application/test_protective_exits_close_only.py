
import pytest
from decimal import Decimal
from types import SimpleNamespace

from crypto_ai_bot.core.application.protective_exits import make_protective_exits

class DummyBus:
    def __init__(self): self.events = []
    async def publish(self, name, payload): self.events.append((name, payload))

class DummyBroker:
    def __init__(self, last): self._last = Decimal(str(last)); self.sells = []
    async def fetch_ticker(self, symbol): return {"last": str(self._last)}
    async def create_market_sell_base(self, symbol, base_amount): self.sells.append((symbol, base_amount)); return {"id":"x"}

class PosRepo:
    def __init__(self, base_qty, avg): self._bq=Decimal(str(base_qty)); self._avg=Decimal(str(avg))
    def get_position(self, symbol): return SimpleNamespace(base_qty=self._bq, avg_entry_price=self._avg)
    def update_max_price(self, symbol, price): pass

class Storage: 
    def __init__(self, base_qty, avg): self.positions = PosRepo(base_qty, avg)

class Settings:
    EXITS_STOP_PCT = Decimal("5")
    EXITS_TAKE_PCT = Decimal("5")
    EXITS_TRAIL_PCT = Decimal("0")
    EXITS_MIN_BASE = Decimal("0")

@pytest.mark.asyncio
async def test_exits_sell_close_only_when_stop_hit():
    broker = DummyBroker(last=90)  # below 5% stop from avg=100
    storage = Storage(base_qty=Decimal("1"), avg=Decimal("100"))
    bus = DummyBus()
    px = make_protective_exits(broker=broker, storage=storage, bus=bus, settings=Settings())
    res = await px.evaluate(symbol="BTC/USDT")
    assert broker.sells and broker.sells[0][1] == Decimal("1")
    assert res and res.get("closed") is True

@pytest.mark.asyncio
async def test_exits_no_position_no_action():
    broker = DummyBroker(last=120)
    storage = Storage(base_qty=Decimal("0"), avg=Decimal("100"))
    bus = DummyBus()
    px = make_protective_exits(broker=broker, storage=storage, bus=bus, settings=Settings())
    res = await px.evaluate(symbol="BTC/USDT")
    assert not broker.sells
    assert res is None
