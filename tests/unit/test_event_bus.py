import asyncio
import pytest
from crypto_ai_bot.core.events.bus import AsyncEventBus

@pytest.mark.asyncio
async def test_subscribe_and_publish_single():
    """Тест: подписка на событие и получение опубликованного события."""
    bus = AsyncEventBus(max_queue=10, concurrency=1)
    received = []
    async def handler(event):
        received.append(event.get("type"))
    bus.subscribe("MyEvent", handler)
    await bus.start()
    await bus.publish({"type": "MyEvent", "payload": {"value": 123}})
    # Даем циклу событий шанс обработать сообщение
    await asyncio.sleep(0)
    await bus.stop()
    assert received == ["MyEvent"]

@pytest.mark.asyncio
async def test_multiple_handlers_for_event():
    """Тест: несколько обработчиков вызываются для одного события."""
    bus = AsyncEventBus(max_queue=5, concurrency=1)
    called = []
    async def handler_a(event):
        called.append("A")
    async def handler_b(event):
        called.append("B")
    bus.subscribe("TestEvent", handler_a)
    bus.subscribe("TestEvent", handler_b)
    await bus.start()
    await bus.publish({"type": "TestEvent", "data": 1})
    await asyncio.sleep(0)
    await bus.stop()
    # Оба обработчика должны быть вызваны по одному разу
    assert "A" in called and "B" in called
    assert called.count("A") == 1
    assert called.count("B") == 1

@pytest.mark.asyncio
async def test_event_ordering_and_concurrency():
    """Тест: проверка последовательности обработки и параллельности по разным ключам."""
    bus = AsyncEventBus(max_queue=10, concurrency=2)
    order = []
    async def handler(event):
        # имитируем некоторую задержку обработки
        await asyncio.sleep(0.01)
        order.append((event.get("key"), event.get("payload")))
    bus.subscribe("KeyEvent", handler)
    await bus.start()
    # Публикуем два события с одним ключом и одно с другим
    await bus.publish({"type": "KeyEvent", "key": "X", "payload": 1})
    await bus.publish({"type": "KeyEvent", "key": "X", "payload": 2})
    await bus.publish({"type": "KeyEvent", "key": "Y", "payload": 3})
    await asyncio.sleep(0.05)
    await bus.stop()
    # События с ключом "X" должны быть обработаны по порядку (1, затем 2)
    x_events = [p for k, p in order if k == "X"]
    assert x_events == [1, 2]
    # Событие с ключом "Y" присутствует в обработанных
    assert any(k == "Y" for k, _ in order)

@pytest.mark.asyncio
async def test_start_stop_health():
    """Тест: проверка статуса запуска и остановки EventBus."""
    bus = AsyncEventBus(max_queue=1, concurrency=1)
    await bus.start()
    health_running = bus.health()
    assert health_running["running"] is True
    await bus.stop()
    health_stopped = bus.health()
    assert health_stopped["running"] is False

@pytest.mark.asyncio
async def test_dlq_and_republish():
    """Тест: попадание событий в DLQ при исключении и повторная публикация."""
    bus = AsyncEventBus(max_queue=5, concurrency=1)
    # Обработчик, всегда выбрасывающий исключение
    async def faulty_handler(event):
        raise RuntimeError("Handler failure")
    # Обработчик, который успешно обрабатывает событие
    received = []
    async def good_handler(event):
        received.append(event.get("payload", {}).get("val"))
    bus.subscribe("ErrorEvent", faulty_handler)
    await bus.start()
    await bus.publish({"type": "ErrorEvent", "payload": {"val": 42}})
    await asyncio.sleep(0)
    await bus.stop()
    # Событие должно попасть в DLQ
    assert bus.dlq_size() == 1
    # Теперь подписываем работающий обработчик и републикуем из DLQ
    bus.subscribe("ErrorEvent", good_handler)
    await bus.start()
    republished = await bus.try_republish_from_dlq(limit=10)
    assert republished >= 1
    await asyncio.sleep(0)
    await bus.stop()
    # DLQ должен быть пуст после успешной обработки
    assert bus.dlq_size() == 0
    # Обработчик good_handler должен получить исходное значение
    assert 42 in received
