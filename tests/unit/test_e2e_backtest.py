## `tests/integration/test_e2e_backtest.py`
import pytest
from decimal import Decimal
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute
@pytest.mark.asyncio
async def test_e2e_buy_then_sell(container):
    buy = await eval_and_execute(
        symbol=container.settings.SYMBOL,
        storage=container.storage,
        broker=container.broker,
        bus=container.bus,
        exchange=container.settings.EXCHANGE,
        fixed_quote_amount=container.settings.FIXED_AMOUNT,
        idempotency_bucket_ms=container.settings.IDEMPOTENCY_BUCKET_MS,
        idempotency_ttl_sec=container.settings.IDEMPOTENCY_TTL_SEC,
        force_action="buy",
        force_amount=Decimal("50"),
        risk_manager=container.risk,
        protective_exits=container.exits,
    )
    assert buy.action == "buy"
    sell = await eval_and_execute(
        symbol=container.settings.SYMBOL,
        storage=container.storage,
        broker=container.broker,
        bus=container.bus,
        exchange=container.settings.EXCHANGE,
        fixed_quote_amount=container.settings.FIXED_AMOUNT,
        idempotency_bucket_ms=container.settings.IDEMPOTENCY_BUCKET_MS,
        idempotency_ttl_sec=container.settings.IDEMPOTENCY_TTL_SEC,
        force_action="sell",
        risk_manager=container.risk,
        protective_exits=container.exits,
    )
    assert sell.action in {"sell", "hold"}