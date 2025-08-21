## `tests/unit/test_storage_repos.py`
from decimal import Decimal
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository
from crypto_ai_bot.core.brokers.base import OrderDTO
def test_idempotency_repo(container):
    idem = container.storage.idempotency
    k = "btc-usdt:buy:1699920000000"
    assert idem.check_and_store(k, ttl_sec=60) is True
    assert idem.check_and_store(k, ttl_sec=60) is False
def test_trades_repo(container):
    sym = container.settings.SYMBOL
    order = OrderDTO(
        id="x1", client_order_id="t-abc", symbol=sym, side="buy",
        amount=Decimal("0.001"), status="closed", filled=Decimal("0.001"), price=Decimal("100"), cost=Decimal("0.1"), timestamp=0
    )
    tid = container.storage.trades.add_from_order(order)
    assert tid is not None
    row = container.storage.trades.find_by_client_order_id("t-abc")
    assert row and row.symbol == sym