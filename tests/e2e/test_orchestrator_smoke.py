import pytest
import asyncio
from unittest.mock import patch, MagicMock
from crypto_ai_bot.utils.decimal import dec

@pytest.mark.asyncio
async def test_orchestrator_start_stop():
    """Тест запуска и остановки оркестратора."""
    with patch('crypto_ai_bot.core.infrastructure.settings.Settings.load') as mock_load:
        # Полный набор настроек
        mock_load.return_value = MagicMock(
            # Основные
            MODE="paper",
            SANDBOX=0,
            EXCHANGE="gateio",
            SYMBOL="BTC/USDT",
            SYMBOLS="",
            
            # Торговля
            FIXED_AMOUNT=50.0,
            PRICE_FEED="fixed",
            FIXED_PRICE=100.0,
            
            # БД
            DB_PATH=":memory:",
            BACKUP_RETENTION_DAYS=30,
            
            # Идемпотентность
            IDEMPOTENCY_BUCKET_MS=60000,
            IDEMPOTENCY_TTL_SEC=3600,
            
            # Риски
            RISK_COOLDOWN_SEC=60,
            RISK_MAX_SPREAD_PCT=0.3,
            RISK_MAX_POSITION_BASE=0.02,
            RISK_MAX_ORDERS_PER_HOUR=6,
            RISK_DAILY_LOSS_LIMIT_QUOTE=100.0,
            
            # Комиссии
            FEE_PCT_ESTIMATE=dec("0.001"),
            RISK_MAX_FEE_PCT=dec("0.001"),
            RISK_MAX_SLIPPAGE_PCT=dec("0.001"),
            
            # HTTP и автостарт
            HTTP_TIMEOUT_SEC=30,
            TRADER_AUTOSTART=0,
            
            # Интервалы (большие чтобы не мешали тесту)
            EVAL_INTERVAL_SEC=999,
            EXITS_INTERVAL_SEC=999,
            RECONCILE_INTERVAL_SEC=999,
            WATCHDOG_INTERVAL_SEC=999,
            DMS_TIMEOUT_MS=120000,
            
            # Защитные выходы
            EXITS_ENABLED=1,
            EXITS_MODE="both",
            EXITS_HARD_STOP_PCT=0.05,
            EXITS_TRAILING_PCT=0.03,
            EXITS_MIN_BASE_TO_EXIT=0.0,
            
            # Telegram
            TELEGRAM_ENABLED=0,
            TELEGRAM_BOT_TOKEN="",
            TELEGRAM_CHAT_ID="",
            
            # API
            API_TOKEN="",
            API_KEY="",
            API_SECRET="",
            POD_NAME="test",
            HOSTNAME="test"
        )
        
        # Импортируем после патча
        from crypto_ai_bot.app.compose import build_container
        
        container = build_container()
        
        # Проверяем что контейнер создался
        assert container is not None
        assert container.orchestrator is not None
        
        # Запуск
        container.orchestrator.start()
        status = container.orchestrator.status()
        assert status["running"] is True
        assert "tasks" in status
        
        # Ждем немного чтобы задачи запустились
        await asyncio.sleep(0.1)
        
        # Остановка
        await container.orchestrator.stop()
        status = container.orchestrator.status()
        assert status["running"] is False