import pytest
from unittest.mock import AsyncMock, MagicMock
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms

@pytest.mark.asyncio
async def test_dms_normal_operation():
    """Тест нормальной работы - регулярные heartbeat."""
    storage = MagicMock()
    broker = AsyncMock()
    
    dms = DeadMansSwitch(
        storage=storage,
        broker=broker,
        symbol="BTC/USDT",
        timeout_ms=1000  # 1 секунда для теста
    )
    
    # Регулярные heartbeat
    dms.beat()
    await asyncio.sleep(0.5)
    dms.beat()
    
    # Проверяем - не должно сработать
    triggered = await dms.check_and_trigger()
    assert triggered is False
    broker.create_market_sell_base.assert_not_called()

@pytest.mark.asyncio
async def test_dms_timeout_triggers():
    """Тест срабатывания при таймауте."""
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=dec("0.001"))
    storage.audit = MagicMock()
    storage.audit.add = MagicMock()  # Исправлено: add вместо log
    
    broker = AsyncMock()
    broker.create_market_sell_base.return_value = MagicMock(id="emergency-123")
    
    dms = DeadMansSwitch(
        storage=storage,
        broker=broker,
        symbol="BTC/USDT",
        timeout_ms=100,  # 100ms для быстрого теста
        action="close"
    )
    
    # Один beat в начале
    dms.beat()
    
    # Ждем больше таймаута
    await asyncio.sleep(0.2)
    
    # Должно сработать
    triggered = await dms.check_and_trigger()
    assert triggered is True
    broker.create_market_sell_base.assert_called_once()
    
    # Повторный вызов не должен сработать
    triggered2 = await dms.check_and_trigger()
    assert triggered2 is False

@pytest.mark.asyncio
async def test_dms_no_position():
    """Тест когда нет позиции для закрытия."""
    storage = MagicMock()
    storage.positions.get_position.return_value = MagicMock(base_qty=dec("0"))
    
    broker = AsyncMock()
    
    dms = DeadMansSwitch(
        storage=storage,
        broker=broker,
        symbol="BTC/USDT",
        timeout_ms=100,
        action="close"
    )
    
    # Ждем таймаут
    await asyncio.sleep(0.2)
    
    triggered = await dms.check_and_trigger()
    assert triggered is True
    broker.create_market_sell_base.assert_not_called()  # Нечего закрывать

@pytest.mark.asyncio
async def test_dms_alert_only():
    """Тест режима только алертов."""
    storage = MagicMock()
    storage.audit = MagicMock()
    storage.audit.add = MagicMock()
    
    broker = AsyncMock()
    
    dms = DeadMansSwitch(
        storage=storage,
        broker=broker,
        symbol="BTC/USDT",
        timeout_ms=100,
        action="alert"  # Только алерты
    )
    
    await asyncio.sleep(0.2)
    
    triggered = await dms.check_and_trigger()
    assert triggered is True
    broker.create_market_sell_base.assert_not_called()
    storage.audit.add.assert_called()  # Должен записать алерт