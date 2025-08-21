## `tests/integration/test_idempotency_flow.py`
import pytest
from decimal import Decimal
from crypto_ai_bot.core.use_cases.place_order import place_market_buy_quote
@pytest.mark.asyncio
async def test_idempotent_buy_duplicate(container):
    symbol = container.settings.SYMBOL
    r1 = await place_market_buy_quote(
        symbol,
        Decimal("20"),
        exchange=container.settings.EXCHANGE,
        storage=container.storage,
        broker=container.broker,
        bus=container.bus,
        idempotency_bucket_ms=container.settings.IDEMPOTENCY_BUCKET_MS,
        idempotency_ttl_sec=container.settings.IDEMPOTENCY_TTL_SEC,
    )
    r2 = await place_market_buy_quote(
        symbol,
        Decimal("20"),
        exchange=container.settings.EXCHANGE,
        storage=container.storage,
        broker=container.broker,
        bus=container.bus,
        idempotency_bucket_ms=container.settings.IDEMPOTENCY_BUCKET_MS,
        idempotency_ttl_sec=container.settings.IDEMPOTENCY_TTL_SEC,
    )
    assert r1.duplicate is False and r2.duplicate is True