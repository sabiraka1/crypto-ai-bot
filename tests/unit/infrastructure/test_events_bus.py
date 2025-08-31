import pytest

from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus


@pytest.mark.asyncio
async def test_event_bus_pub_sub():
    bus = AsyncEventBus()
    got = {}

    async def handler(payload):
        got.update(payload)

    bus.subscribe("topic", handler)
    await bus.publish("topic", {"x": 1})
    # publish — await-ится, хэндлер уже выполнен
    assert got == {"x": 1}
