from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch


@pytest.mark.asyncio
async def test_dms_triggers_and_publishes(mock_storage, mock_broker):
    # Настраиваем позицию правильно через мок
    mock_storage.positions.get_position.return_value = type("Position", (), {
        "base_qty": Decimal("0.1"),
        "avg_entry_price": Decimal("100")
    })()
    
    # Создаем мок для ticker который возвращает объект, а не dict
    broker = mock_broker
    
    # Переопределяем fetch_ticker чтобы возвращал объект
    async def _ticker_side_effect(_):
        if not hasattr(_ticker_side_effect, "n"):
            _ticker_side_effect.n = 0
        _ticker_side_effect.n += 1
        last = Decimal("100") if _ticker_side_effect.n == 1 else Decimal("95")
        # Возвращаем объект с атрибутами, а не dict
        return Mock(last=last, bid=last, ask=last)

    broker.fetch_ticker = AsyncMock(side_effect=_ticker_side_effect)

    bus = type("Bus", (), {"publish": AsyncMock()})()

    dms = DeadMansSwitch(
        storage=mock_storage,
        broker=broker,
        symbol="BTC/USDT",
        timeout_ms=0,
        rechecks=1,
        recheck_delay_sec=0.0,
        max_impact_pct=0,
        bus=bus,
    )

    await dms.check()

    # Один sell выполнен и событие отправлено
    broker.create_market_sell_base.assert_awaited()
    bus.publish.assert_awaited()


@pytest.mark.asyncio
async def test_dms_skips_when_impact_limit(mock_storage, mock_broker):
    # Настраиваем позицию
    mock_storage.positions.get_position.return_value = type("Position", (), {
        "base_qty": Decimal("0.1"),
        "avg_entry_price": Decimal("100")
    })()
    
    # max_impact_pct > 0 — всегда skip
    bus = type("Bus", (), {"publish": AsyncMock()})()
    dms = DeadMansSwitch(
        storage=mock_storage,
        broker=mock_broker,
        symbol="BTC/USDT",
        timeout_ms=0,
        rechecks=0,
        recheck_delay_sec=0.0,
        max_impact_pct=10,  # ограничение по влиянию
        bus=bus,
    )
    await dms.check()
    mock_broker.create_market_sell_base.assert_not_awaited()