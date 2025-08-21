## `tests/unit/test_events_bus.py`
import asyncio
import pytest
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.utils.exceptions import ValidationError
@pytest.mark.asyncio
async def test_per_key_order_and_dlq():
    bus = AsyncEventBus(max_attempts=2, backoff_base_ms=10)
    seen = []
    dlq_seen = []
    async def ok_handler(evt):
        seen.append(evt.payload["i"])
    async def bad_handler(evt):
        raise ValidationError("boom")
    async def dlq_handler(evt):
        dlq_seen.append(evt.payload.get("handler"))
    bus.subscribe("t", ok_handler)
    bus.subscribe("t", bad_handler)
    bus.subscribe_dlq(dlq_handler)
    for i in range(5):
        await bus.publish("t", {"i": i}, key="k")
    await asyncio.sleep(0.2)
    assert seen == list(range(5))
    assert "bad_handler" in dlq_seen or any("bad_handler" in str(x) for x in dlq_seen)
    await bus.close()