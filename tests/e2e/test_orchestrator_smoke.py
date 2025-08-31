import asyncio
from unittest.mock import MagicMock, patch

import pytest

from crypto_ai_bot.app.compose import build_container_async
from crypto_ai_bot.utils.decimal import dec


@pytest.mark.asyncio
async def test_orchestrator_start_stop():
    """Тест запуска и остановки любого оркестратора из контейнера."""
    with patch("crypto_ai_bot.core.infrastructure.settings.Settings.load") as mock_load:
        # Полный набор настроек (как было), только используем async контейнер
        mock_load.return_value = MagicMock(
            MODE="paper",
            SANDBOX=0,
            EXCHANGE="gateio",
            SYMBOL="BTC/USDT",
            SYMBOLS="",
            FIXED_AMOUNT=50.0,
            PRICE_FEED="fixed",
            FIXED_PRICE=100.0,
            DB_PATH=":memory:",
            BACKUP_RETENTION_DAYS=30,
            IDEMPOTENCY_BUCKET_MS=60000,
            IDEMPOTENCY_TTL_SEC=3600,
            RISK_COOLDOWN_SEC=60,
            RISK_MAX_SPREAD_PCT=0.3,
            RISK_MAX_POSITION_BASE=0.02,
            RISK_MAX_ORDERS_PER_HOUR=6,
            RISK_DAILY_LOSS_LIMIT_QUOTE=dec("100"),
            FEE_PCT_ESTIMATE=dec("0.001"),
            RISK_MAX_FEE_PCT=dec("0.001"),
            RISK_MAX_SLIPPAGE_PCT=dec("0.001"),
            HTTP_TIMEOUT_SEC=30,
            TRADER_AUTOSTART=0,
            # Интервалы большие, чтобы фоновые задачи не мешали управлению в тесте
            EVAL_INTERVAL_SEC=999,
            EXITS_INTERVAL_SEC=999,
            RECONCILE_INTERVAL_SEC=999,
            WATCHDOG_INTERVAL_SEC=999,
            DMS_TIMEOUT_MS=120000,
            EXITS_ENABLED=1,
            EXITS_MODE="both",
            EXITS_HARD_STOP_PCT=0.05,
            EXITS_TRAILING_PCT=0.03,
            EXITS_MIN_BASE_TO_EXIT=0.0,
            TELEGRAM_ENABLED=0,
            TELEGRAM_BOT_TOKEN="",
            TELEGRAM_CHAT_ID="",
            API_TOKEN="",
            API_KEY="",
            API_SECRET="",
            POD_NAME="test",
            HOSTNAME="test",
        )

        container = await build_container_async()
        assert container is not None
        assert isinstance(container.orchestrators, dict) and container.orchestrators

        # Берём первый доступный оркестратор по символу
        symbol, orch = next(iter(container.orchestrators.items()))

        # Старт/стоп — именно await, потому что методы асинхронные
        await orch.start()
        status = orch.status()
        assert status.get("started", status.get("running")) in (True,)

        await asyncio.sleep(0.1)

        await orch.stop()
        status = orch.status()
        assert status.get("started", status.get("running")) in (False,)
