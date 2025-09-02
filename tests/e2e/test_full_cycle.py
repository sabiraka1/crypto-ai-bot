import asyncio
from unittest.mock import patch
import pytest

@pytest.mark.asyncio
async def test_full_trading_cycle_minimal(monkeypatch):
    """
    Упрощённый e2e: запускаем оркестратор на бумажном брокере и in-memory bus.
    Внешний Redis не используется (монкипатчим RedisBus -> DummyBus).
    """
    # Подменяем RedisBus на «пустой» bus, чтобы не требовать запущенный Redis
    from crypto_ai_bot.core.infrastructure.events import redis_bus as rb

    class DummyBus:
        def __init__(self, *_args, **_kwargs):
            self.published = []

        async def start(self):
            return None

        async def stop(self):
            return None

        async def publish(self, topic, payload, key=None):
            self.published.append((topic, payload, key))

        # На всякий случай — если где-то подписка дернётся
        async def subscribe(self, *_topics):
            return None

    monkeypatch.setattr(rb, "RedisBus", DummyBus, raising=True)

    # Теперь можно собирать контейнер, не опасаясь внешних сервисов
    from crypto_ai_bot.app.compose import build_container_async

    with patch("crypto_ai_bot.core.infrastructure.settings.Settings.load") as mock_load:
        s = mock_load.return_value
        # Минимальные настройки, быстрые интервалы, in-memory БД
        s.MODE = "paper"
        s.EXCHANGE = "gateio"
        s.SYMBOL = "BTC/USDT"
        s.SYMBOLS = ""
        s.FIXED_AMOUNT = 10.0
        s.PRICE_FEED = "fixed"
        s.FIXED_PRICE = 100.0
        s.DB_PATH = ":memory:"
        s.BACKUP_RETENTION_DAYS = 0
        s.IDEMPOTENCY_BUCKET_MS = 60000
        s.IDEMPOTENCY_TTL_SEC = 3600
        s.RISK_COOLDOWN_SEC = 0
        s.RISK_MAX_SPREAD_PCT = 5.0
        s.RISK_MAX_POSITION_BASE = 10.0
        s.RISK_MAX_ORDERS_PER_HOUR = 999
        s.RISK_DAILY_LOSS_LIMIT_QUOTE = 0
        s.FEE_PCT_ESTIMATE = 0
        s.RISK_MAX_FEE_PCT = 1
        s.RISK_MAX_SLIPPAGE_PCT = 1
        s.HTTP_TIMEOUT_SEC = 5
        s.TRADER_AUTOSTART = 0
        s.EVAL_INTERVAL_SEC = 0.1
        s.EXITS_INTERVAL_SEC = 0.1
        s.RECONCILE_INTERVAL_SEC = 0.1
        s.WATCHDOG_INTERVAL_SEC = 0.1
        s.DMS_TIMEOUT_MS = 5000
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

    assert container.orchestrators
    symbol, orch = next(iter(container.orchestrators.items()))

    await orch.start()
    await asyncio.sleep(0.2)
    await orch.stop()
