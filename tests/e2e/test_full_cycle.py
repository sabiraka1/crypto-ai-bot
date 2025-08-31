import asyncio
from unittest.mock import patch

import pytest

from crypto_ai_bot.app.compose import build_container_async


@pytest.mark.asyncio
async def test_full_trading_cycle_minimal():
    """
    Упрощённый e2e: запускаем оркестратор, ждём немного тиков и останавливаем.
    Проверяем лишь, что он живёт/останавливается корректно.
    """
    with patch("crypto_ai_bot.core.infrastructure.settings.Settings.load") as mock_load:
        # Минимальный набор быстрых интервалов, in-memory БД — чтобы тест был резвым
        s = mock_load.return_value
        s.MODE = "paper"
        s.EXCHANGE = "gateio"
        s.SYMBOL = "BTC/USDT"
        s.SYMBOLS = ""
        s.FIXED_AMOUNT = 50.0
        s.PRICE_FEED = "fixed"
        s.FIXED_PRICE = 100.0
        s.DB_PATH = ":memory:"
        s.BACKUP_RETENTION_DAYS = 0
        s.IDEMPOTENCY_BUCKET_MS = 60000
        s.IDEMPOTENCY_TTL_SEC = 3600
        s.RISK_COOLDOWN_SEC = 1
        s.RISK_MAX_SPREAD_PCT = 1.0
        s.RISK_MAX_POSITION_BASE = 1.0
        s.RISK_MAX_ORDERS_PER_HOUR = 100
        s.RISK_DAILY_LOSS_LIMIT_QUOTE = 0
        s.FEE_PCT_ESTIMATE = 0
        s.RISK_MAX_FEE_PCT = 1
        s.RISK_MAX_SLIPPAGE_PCT = 1
        s.HTTP_TIMEOUT_SEC = 5
        s.TRADER_AUTOSTART = 0
        s.EVAL_INTERVAL_SEC = 0.2
        s.EXITS_INTERVAL_SEC = 0.2
        s.RECONCILE_INTERVAL_SEC = 0.2
        s.WATCHDOG_INTERVAL_SEC = 0.2
        s.DMS_TIMEOUT_MS = 5_000
        s.EXITS_ENABLED = 0
        s.EXITS_MODE = "both"
        s.EXITS_HARD_STOP_PCT = 0.05
        s.EXITS_TRAILING_PCT = 0.03
        s.EXITS_MIN_BASE_TO_EXIT = 0.0
        s.TELEGRAM_ENABLED = 0
        s.TELEGRAM_BOT_TOKEN = ""
        s.TELEGRAM_CHAT_ID = ""
        s.API_TOKEN = ""
        s.API_KEY = ""
        s.API_SECRET = ""
        s.POD_NAME = "test"
        s.HOSTNAME = "test"

        container = await build_container_async()
        symbol, orch = next(iter(container.orchestrators.items()))

        await orch.start()
        await asyncio.sleep(0.6)  # даём нескольким задачам «подышать»
        st = orch.status()
        assert st.get("started", st.get("running")) in (True,)

        await orch.stop()
        st2 = orch.status()
        assert st2.get("started", st2.get("running")) in (False,)
