import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms


@pytest.fixture(autouse=True)
def disable_redis():
    """Отключаем Redis для всех тестов."""
    os.environ["EVENT_BUS_URL"] = ""
    yield


@pytest.fixture
def temp_db():
    """Временная БД для тестов с применением миграций."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Применяем все миграции
    run_migrations(
        conn,
        now_ms=now_ms(),
        db_path=db_path,
        do_backup=False,
        backup_retention_days=0
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
    
    class MockSettings:
        # Основные
        MODE: str = "paper"
        SANDBOX: int = 0
        EXCHANGE: str = "gateio"
        SYMBOL: str = "BTC/USDT"
        SYMBOLS: str = ""

        # Торговля
        FIXED_AMOUNT: float = 50.0
        PRICE_FEED: str = "fixed"
        FIXED_PRICE: float = 100.0

        # БД
        DB_PATH: str = ":memory:"
        BACKUP_RETENTION_DAYS: int = 30

        # Event Bus - ВАЖНО: пустая строка отключает Redis
        EVENT_BUS_URL: str = ""

        # Идемпотентность
        IDEMPOTENCY_BUCKET_MS: int = 60000
        IDEMPOTENCY_TTL_SEC: int = 3600

        # Риски
        RISK_COOLDOWN_SEC: int = 60
        RISK_MAX_SPREAD_PCT: float = 0.3
        RISK_MAX_POSITION_BASE: float = 0.02
        RISK_MAX_ORDERS_PER_HOUR: int = 6
        RISK_DAILY_LOSS_LIMIT_QUOTE: float = 100.0
        RISK_MAX_ORDERS_5M: int = 10
        SAFETY_MAX_TURNOVER_QUOTE_PER_DAY: float = 10000.0
        RISK_MAX_TURNOVER_DAY: float = 10000.0

        # Комиссии и проскальзывание
        FEE_PCT_ESTIMATE: Any = dec("0.001")
        RISK_MAX_FEE_PCT: Any = dec("0.001")
        RISK_MAX_SLIPPAGE_PCT: Any = dec("0.001")

        # HTTP и автостарт
        HTTP_TIMEOUT_SEC: int = 30
        HTTP_PROXY: str = ""
        TRADER_AUTOSTART: int = 0

        # Интервалы
        EVAL_INTERVAL_SEC: float = 0.01
        EXITS_INTERVAL_SEC: float = 0.01
        RECONCILE_INTERVAL_SEC: float = 0.01
        WATCHDOG_INTERVAL_SEC: float = 0.01
        SETTLEMENT_INTERVAL_SEC: float = 0.01

        # DMS
        DMS_TIMEOUT_MS: int = 120000
        DMS_RECHECKS: int = 2
        DMS_RECHECK_DELAY_SEC: float = 3.0
        DMS_MAX_IMPACT_PCT: float = 0.0

        # Защитные выходы
        EXITS_ENABLED: int = 1
        EXITS_MODE: str = "both"
        EXITS_STOP_PCT: float = 5.0
        EXITS_TAKE_PCT: float = 10.0
        EXITS_TRAIL_PCT: float = 3.0
        EXITS_MIN_BASE: float = 0.0
        
        # Альтернативные названия для совместимости
        EXITS_HARD_STOP_PCT: float = 5.0
        EXITS_TAKE_PROFIT_PCT: float = 10.0
        EXITS_TRAILING_PCT: float = 3.0
        EXITS_MIN_BASE_TO_EXIT: float = 0.0

        # Telegram
        TELEGRAM_ENABLED: int = 0
        TELEGRAM_BOT_TOKEN: str = ""
        TELEGRAM_CHAT_ID: str = ""
        TELEGRAM_BOT_COMMANDS_ENABLED: bool = False
        TELEGRAM_ALLOWED_USERS: str = ""

        # API/Keys
        API_TOKEN: str = ""
        API_KEY: str = ""
        API_SECRET: str = ""
        API_PASSWORD: str = ""
        POD_NAME: str = "test-pod"
        HOSTNAME: str = "test-host"
        
        # Rate limiting
        BROKER_RATE_RPS: int = 8
        BROKER_RATE_BURST: int = 16
        
        def __getattr__(self, name: str) -> Any:
            # Возвращаем None для неопределенных атрибутов
            return None

    return MockSettings()


@pytest.fixture
def mock_broker():
    """Мок брокера с простыми объектами-ответами (атрибуты как у CCXT-DTO)."""
    broker = AsyncMock()
    broker.exchange = "paper"
    
    broker.fetch_ticker.return_value = {
        "symbol": "BTC/USDT",
        "last": "50000",
        "bid": "49950",
        "ask": "50050",
        "timestamp": 1700000000000,
    }
    
    broker.fetch_balance.return_value = {
        "USDT": {
            "free": "1000",
            "used": "0",
            "total": "1000"
        },
        "BTC": {
            "free": "0.001",
            "used": "0",
            "total": "0.001"
        }
    }
    
    broker.create_market_buy_quote.return_value = {
        "id": "123",
        "clientOrderId": "test-buy-123",
        "client_order_id": "test-buy-123",
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": "0.001",
        "status": "closed",
        "filled": "0.001",
        "price": "50000",
        "cost": "50",
        "fee_quote": "0.05",
        "timestamp": 1700000000000,
        "ts_ms": 1700000000000
    }
    
    broker.create_market_sell_base.return_value = {
        "id": "124",
        "clientOrderId": "test-sell-124",
        "client_order_id": "test-sell-124",
        "symbol": "BTC/USDT",
        "side": "sell",
        "amount": "0.001",
        "status": "closed",
        "filled": "0.001",
        "price": "50000",
        "cost": "50",
        "fee_quote": "0.05",
        "timestamp": 1700000000000,
        "ts_ms": 1700000000000
    }
    
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