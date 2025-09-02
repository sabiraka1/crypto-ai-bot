import asyncio
from unittest.mock import patch
import pytest

@pytest.mark.asyncio
async def test_orchestrator_start_stop(monkeypatch):
    """
    Старт/стоп оркестратора через in-memory bus (без Redis).
    """
    from crypto_ai_bot.core.infrastructure.events import redis_bus as rb

    class DummyBus:
        def __init__(self, *_a, **_kw):
            pass
        async def start(self): pass
        async def stop(self): pass
        async def publish(self, *_a, **_kw): pass
        async def subscribe(self, *_a, **_kw): pass

    monkeypatch.setattr(rb, "RedisBus", DummyBus, raising=True)

    from crypto_ai_bot.app.compose import build_container_async

    with patch("crypto_ai_bot.core.infrastructure.settings.Settings.load") as mock_load:
        mock_load.return_value = type("S", (), dict(
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
            RISK_COOLDOWN_SEC=0,
            RISK_MAX_SPREAD_PCT=5.0,
            RISK_MAX_POSITION_BASE=10.0,
            RISK_MAX_ORDERS_PER_HOUR=999,
            RISK_DAILY_LOSS_LIMIT_QUOTE=0,
            FEE_PCT_ESTIMATE=0,
            RISK_MAX_FEE_PCT=1,
            RISK_MAX_SLIPPAGE_PCT=1,
            HTTP_TIMEOUT_SEC=5,
            TRADER_AUTOSTART=0,
            EVAL_INTERVAL_SEC=0.1,
            EXITS_INTERVAL_SEC=0.1,
            RECONCILE_INTERVAL_SEC=0.1,
            WATCHDOG_INTERVAL_SEC=0.1,
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
        ))()

        container = await build_container_async()

    assert container and container.orchestrators
    _, orch = next(iter(container.orchestrators.items()))
    await orch.start()
    await asyncio.sleep(0.1)
    await orch.stop()
