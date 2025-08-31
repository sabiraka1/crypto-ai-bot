import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from crypto_ai_bot.utils.decimal import dec


@pytest.fixture
def temp_db():
    """Временная БД для тестов."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Базовые таблицы (минимально необходимые для facades)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS positions(
            symbol TEXT PRIMARY KEY,
            base_qty NUMERIC NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            amount NUMERIC NOT NULL DEFAULT 0,
            price NUMERIC NOT NULL DEFAULT 0,
            cost NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'closed',
            ts_ms INTEGER NOT NULL,
            created_at_ms INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency(
            key TEXT PRIMARY KEY,
            ts_ms INTEGER NOT NULL,
            ttl_sec INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            payload TEXT,
            ts_ms INTEGER NOT NULL
        )
        """
    )
    conn.commit()

    try:
        yield conn, db_path
    finally:
        conn.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def mock_settings():
    """Полный мок настроек со многими полями (совместим с текущими Settings)."""
    from crypto_ai_bot.core.infrastructure.settings import Settings

    return Settings(
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

        # Комиссии и проскальзывание
        FEE_PCT_ESTIMATE=dec("0.001"),
        RISK_MAX_FEE_PCT=dec("0.001"),
        RISK_MAX_SLIPPAGE_PCT=dec("0.001"),

        # HTTP и автостарт
        HTTP_TIMEOUT_SEC=30,
        TRADER_AUTOSTART=0,

        # Интервалы
        EVAL_INTERVAL_SEC=0.01,
        EXITS_INTERVAL_SEC=0.01,
        RECONCILE_INTERVAL_SEC=0.01,
        WATCHDOG_INTERVAL_SEC=0.01,
        SETTLEMENT_INTERVAL_SEC=0.01,
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
        TELEGRAM_BOT_COMMANDS_ENABLED=0,
        TELEGRAM_ALLOWED_USERS="",

        # API/Keys
        API_TOKEN="",
        API_KEY="",
        API_SECRET="",
        POD_NAME="test-pod",
        HOSTNAME="test-host",
    )


@pytest.fixture
def mock_broker():
    """Мок брокера с простыми объектами-ответами (атрибуты как у CCXT-DTO)."""
    broker = AsyncMock()
    broker.fetch_ticker.return_value = MagicMock(
        symbol="BTC/USDT",
        last=dec("50000"),
        bid=dec("49950"),
        ask=dec("50050"),
        timestamp=1700000000000,
    )
    broker.fetch_balance.return_value = MagicMock(
        free_quote=dec("1000"),
        free_base=dec("0.001"),
    )
    broker.create_market_buy_quote.return_value = MagicMock(
        id="123",
        client_order_id="test-buy-123",
        symbol="BTC/USDT",
        side="buy",
        amount=dec("0.001"),
        status="closed",
        filled=dec("0.001"),
        timestamp=1700000000000,
    )
    broker.create_market_sell_base.return_value = MagicMock(
        id="124",
        client_order_id="test-sell-124",
        symbol="BTC/USDT",
        side="sell",
        amount=dec("0.001"),
        status="closed",
        filled=dec("0.001"),
        timestamp=1700000000000,
    )
    return broker


@pytest.fixture
def mock_storage(temp_db):
    """Хранилище на временной БД (настоящая facade)."""
    from crypto_ai_bot.core.infrastructure.storage.facade import Storage

    conn, _ = temp_db
    return Storage.from_connection(conn)


@pytest.fixture
def event_loop():
    """Выделяем отдельный event loop для async-тестов."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        yield loop
    finally:
        loop.close()
