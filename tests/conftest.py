import pytest
import sqlite3
import tempfile
from pathlib import Path
from decimal import Decimal

@pytest.fixture
def temp_db():
    """Временная БД для тестов."""
    with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn, db_path
    conn.close()
    Path(db_path).unlink(missing_ok=True)

@pytest.fixture
def mock_settings():
    """Мок настроек."""
    from crypto_ai_bot.core.infrastructure.settings import Settings
    return Settings(
        MODE="paper", SANDBOX=0, EXCHANGE="gateio", SYMBOL="BTC/USDT",
        SYMBOLS="", FIXED_AMOUNT=50.0, PRICE_FEED="fixed", FIXED_PRICE=100.0,
        DB_PATH=":memory:", BACKUP_RETENTION_DAYS=30,
        IDEMPOTENCY_BUCKET_MS=60000, IDEMPOTENCY_TTL_SEC=3600,
        RISK_COOLDOWN_SEC=60, RISK_MAX_SPREAD_PCT=0.3,
        RISK_MAX_POSITION_BASE=0.02, RISK_MAX_ORDERS_PER_HOUR=6,
        RISK_DAILY_LOSS_LIMIT_QUOTE=100.0,
        FEE_PCT_ESTIMATE=Decimal("0.001"), RISK_MAX_FEE_PCT=Decimal("0.001"),
        RISK_MAX_SLIPPAGE_PCT=Decimal("0.001"),
        EVAL_INTERVAL_SEC=60, EXITS_INTERVAL_SEC=5,
        RECONCILE_INTERVAL_SEC=60, WATCHDOG_INTERVAL_SEC=15,
        DMS_TIMEOUT_MS=120000, EXITS_ENABLED=1, EXITS_MODE="both",
        EXITS_HARD_STOP_PCT=0.05, EXITS_TRAILING_PCT=0.03,
        EXITS_MIN_BASE_TO_EXIT=0.0, API_TOKEN="", API_KEY="", API_SECRET="",
        POD_NAME="", HOSTNAME=""
    )