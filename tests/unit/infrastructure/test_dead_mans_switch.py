from decimal import Decimal
from unittest.mock import AsyncMock, Mock
import pytest

from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.infrastructure.storage.repositories import Storage

@pytest.mark.asyncio
async def test_dms_triggers_and_publishes(mock_storage: Storage, mock_broker):
    # Позиция достаточно большая, чтобы пройти возможные внутренние пороги
    mock_storage.positions.get_position.return_value = type("Position", (), {
        "base_qty": Decimal("1.0"),
        "avg_entry_price": Decimal("100")
    })()

    broker = mock_broker

    # Тикер как объект с атрибутами (не dict), с падением цены
    async def _ticker_side_effect(_):
        if not hasattr(_ticker_side_effect, "n"):
            _ticker_side_effect.n = 0
        _ticker_side_effect.n += 1
        last = Decimal("100") if _ticker_side_effect.n == 1 else Decimal("95")
        return Mock(last=last, bid=last, ask=last)

    broker.fetch_ticker = AsyncMock(side_effect=_ticker_side_effect)
    broker.create_market_sell_base = AsyncMock()

    bus = type("Bus", (), {"publish": AsyncMock()})()

    dms = DeadMansSwitch(
        storage=mock_storage,
        broker=broker,
        symbol="BTC/USDT",
        timeout_ms=0,          # сразу считаем таймаут наступившим
        rechecks=0,            # без дополнительных проверок, чтобы тест был быстрым
        recheck_delay_sec=0.0,
        max_impact_pct=100,    # не блокируем по impact
        bus=bus,
    )

    await dms.check()

    broker.create_market_sell_base.assert_awaited()
    bus.publish.assert_awaited()
