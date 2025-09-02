import pytest

from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus, Event


@pytest.mark.asyncio
async def test_event_bus_pub_sub():
    bus = AsyncEventBus()
    got = {}

    async def handler(evt):
        # handler получает Event объект, нужно извлечь payload
        if isinstance(evt, Event):
            got.update(evt.payload)
        else:
            got.update(evt)

    bus.subscribe("topic", handler)
    await bus.publish("topic", {"x": 1})
    # publish — await-ится, хэндлер уже выполнен
    assert got == {"x": 1}