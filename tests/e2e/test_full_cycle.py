import pytest
import asyncio
from unittest.mock import patch
from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.utils.decimal import dec

@pytest.mark.asyncio
async def test_full_trading_cycle():
    """E2E тест полного торгового цикла."""
    with patch('crypto_ai_bot.core.infrastructure.settings.Settings.load') as mock_load:
        # Настройки для быстрого теста
        mock_load.return_value.MODE = "paper"
        mock_load.return_value.SYMBOL = "BTC/USDT"
        mock_load.return_value.FIXED_AMOUNT = 50.0
        mock_load.return_value.DB_PATH = ":memory:"
        mock_load.return_value.EVAL_INTERVAL_SEC = 0.5
        mock_load.return_value.EXITS_INTERVAL_SEC = 0.5
        mock_load.return_value.RECONCILE_INTERVAL_SEC = 1.0
        mock_load.return_value.WATCHDOG_INTERVAL_SEC = 1.0
        
        # Все остальные обязательные поля
        for field in [
            'SANDBOX', 'EXCHANGE', 'SYMBOLS', 'PRICE_FEED', 'FIXED_PRICE',
            'BACKUP_RETENTION_DAYS', 'IDEMPOTENCY_BUCKET_MS', 'IDEMPOTENCY_TTL_SEC',
            'RISK_COOLDOWN_SEC', 'RISK_MAX_SPREAD_PCT', 'RISK_MAX_POSITION_BASE',
            'RISK_MAX_ORDERS_PER_HOUR', 'RISK_DAILY_LOSS_LIMIT_QUOTE',
            'FEE_PCT_ESTIMATE', 'RISK_MAX_FEE_PCT', 'RISK_MAX_SLIPPAGE_PCT',
            'HTTP_TIMEOUT_SEC', 'TRADER_AUTOSTART', 'DMS_TIMEOUT_MS',
            'EXITS_ENABLED', 'EXITS_MODE', 'EXITS_HARD_STOP_PCT',
            'EXITS_TRAILING_PCT', 'EXITS_MIN_BASE_TO_EXIT',
            'TELEGRAM_ENABLED', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
            'API_TOKEN', 'API_KEY', 'API_SECRET', 'POD_NAME', 'HOSTNAME'
        ]:
            if not hasattr(mock_load.return_value, field):
                setattr(mock_load.return_value, field, 
                       0 if 'ENABLED' in field or 'SEC' in field else "")
        
        container = build_container()
        
        # Запускаем оркестратор
        container.orchestrator.start()
        
        # Даем время на несколько циклов
        await asyncio.sleep(2.0)
        
        # Проверяем статус
        status = container.orchestrator.status()
        assert status["running"] is True
        assert all(not task_done for task_done in status["tasks"].values())
        
        # Проверяем что есть heartbeat
        assert status.get("last_beat_ms", 0) > 0
        
        # Останавливаем
        await container.orchestrator.stop()
        
        # Проверяем что остановлен
        status_after = container.orchestrator.status()
        assert status_after["running"] is False