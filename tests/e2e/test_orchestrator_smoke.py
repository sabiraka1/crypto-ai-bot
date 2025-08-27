import pytest
import asyncio
from unittest.mock import patch, MagicMock
from crypto_ai_bot.app.compose import build_container

@pytest.mark.asyncio
async def test_orchestrator_start_stop():
    with patch('crypto_ai_bot.core.infrastructure.settings.Settings.load') as mock_settings:
        mock_settings.return_value = MagicMock(
            MODE="paper", EXCHANGE="gateio", SYMBOL="BTC/USDT",
            DB_PATH=":memory:", FIXED_AMOUNT=50,
            EVAL_INTERVAL_SEC=999, EXITS_INTERVAL_SEC=999,
            RECONCILE_INTERVAL_SEC=999, WATCHDOG_INTERVAL_SEC=999
        )
        
        container = build_container()
        
        # Запуск
        container.orchestrator.start()
        status = container.orchestrator.status()
        assert status["running"] is True
        
        # Ждем немного
        await asyncio.sleep(0.1)
        
        # Остановка
        await container.orchestrator.stop()
        status = container.orchestrator.status()
        assert status["running"] is False