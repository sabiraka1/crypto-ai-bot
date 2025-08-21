## `tests/unit/test_protective_exits.py`
import asyncio
from decimal import Decimal
from crypto_ai_bot.core.risk.protective_exits import ProtectiveExits
from crypto_ai_bot.core.brokers.base import OrderDTO
def test_protective_exits_plan(container):
    exits = ProtectiveExits(storage=container.storage, bus=container.bus)
    order = OrderDTO(
        id="1", client_order_id="t-1", symbol=container.settings.SYMBOL,
        side="buy", amount=Decimal("0.01"), status="closed", filled=Decimal("0.01"),
        price=Decimal("100"), cost=Decimal("1"), timestamp=0
    )
    plan = asyncio.get_event_loop().run_until_complete(exits.ensure(symbol=container.settings.SYMBOL, order=order))
    assert plan and float(plan.tp_price) > 100 and float(plan.sl_price) < 100