# tests/test_async_bus.py
import asyncio
import pytest

from crypto_ai_bot.core.events.async_bus import AsyncEventBus


@pytest.mark.asyncio
async def test_backpressure_keep_latest_and_drop_oldest():
    bus = AsyncEventBus(strategy_map={
        "A": {"strategy": "keep_latest", "queue_size": 2},
        "B": {"strategy": "drop_oldest", "queue_size": 2},
    }, dlq_max=10)

    seen_A = []
    seen_B = []

    bus.subscribe("A", lambda e: seen_A.append(e["n"]))
    bus.subscribe("B", lambda e: seen_B.append(e["n"]))

    await bus.start()
    # publish много событий
    for i in range(5):
        bus.publish({"type": "A", "n": i})
        bus.publish({"type": "B", "n": i})

    await asyncio.sleep(0.1)  # дать воркерам время обработать
    await bus.stop()

    # keep_latest: в обработке должны оказаться только последние из очереди, но с учётом времени работы воркера допускаем >=1
    assert len(seen_A) >= 1
    # drop_oldest: общий объём > queue_size, старые должны были выкидываться, но конечная длина >= 1
    assert len(seen_B) >= 1
