import pytest
import asyncio
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisBus

@pytest.mark.asyncio
async def test_publish_works_without_redis():
    # Use an obviously invalid URL to force fallback
    bus = RedisBus(url="redis://invalid-host:6379/0")
    await bus.start()
    got = []
    bus.subscribe("t", lambda p: got.append(p))
    n = await bus.publish("t", {"k": 1})
    assert n == 1
    assert got == [{"k": 1}]
    await bus.stop()
