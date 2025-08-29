import pytest
import asyncio
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus, Event

@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    """Тест публикации и подписки."""
    bus = AsyncEventBus()
    received = []
    
    async def handler(event: Event):
        received.append(event)
    
    bus.subscribe("test.topic", handler)
    
    result = await bus.publish("test.topic", {"data": "test"}, key="key1")
    
    assert result["ok"] is True
    assert result["delivered"] == 1
    assert len(received) == 1
    assert received[0].topic == "test.topic"
    assert received[0].payload["data"] == "test"

@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    """Тест множественных подписчиков."""
    bus = AsyncEventBus()
    received1 = []
    received2 = []
    
    async def handler1(event: Event):
        received1.append(event)
    
    async def handler2(event: Event):
        received2.append(event)
    
    bus.subscribe("test.topic", handler1)
    bus.subscribe("test.topic", handler2)
    
    result = await bus.publish("test.topic", {"data": "test"})
    
    assert result["delivered"] == 2
    assert len(received1) == 1
    assert len(received2) == 1

@pytest.mark.asyncio
async def test_event_bus_no_subscribers():
    """Тест публикации без подписчиков."""
    bus = AsyncEventBus()
    
    result = await bus.publish("no.subscribers", {"data": "test"})
    
    assert result["ok"] is True
    assert result["delivered"] == 0

@pytest.mark.asyncio
async def test_event_bus_dlq():
    """Тест DLQ при ошибке обработчика."""
    bus = AsyncEventBus(max_attempts=2, backoff_base_ms=10)
    dlq_received = []
    
    async def failing_handler(event: Event):
        raise ValueError("Test error")
    
    async def dlq_handler(event: Event):
        dlq_received.append(event)
    
    bus.subscribe("test.fail", failing_handler)
    bus.subscribe_dlq(dlq_handler)
    
    await bus.publish("test.fail", {"data": "test"})
    
    # Даем время на retry и DLQ
    await asyncio.sleep(0.1)
    
    assert len(dlq_received) == 1
    assert dlq_received[0].topic == "__dlq__"
    assert "error" in dlq_received[0].payload

@pytest.mark.asyncio
async def test_event_bus_retry_success():
    """Тест успешного retry."""
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=10)
    attempts = []
    
    async def flaky_handler(event: Event):
        attempts.append(1)
        if len(attempts) < 2:
            raise ValueError("Temporary error")
        # Успех на второй попытке
    
    bus.subscribe("test.retry", flaky_handler)
    
    result = await bus.publish("test.retry", {"data": "test"})
    
    await asyncio.sleep(0.1)
    
    assert result["ok"] is True
    assert len(attempts) == 2  # Два вызова - первый неудачный, второй успешный