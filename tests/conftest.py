# --- psutil stub for tests (put at very top of tests/conftest.py) ---
# Делает тесты стабильными на CI/Windows без настоящего psutil
import sys, types, time

if "psutil" not in sys.modules:
    # Лёгкая заглушка, которую используют utils/monitoring.py
    _vmem = types.SimpleNamespace(
        percent=42.0,
        total=16 * 1024**3,
        available=8 * 1024**3,
    )
    _disk = types.SimpleNamespace(
        total=1_000_000_000,
        used=200_000_000,
        free=800_000_000,
        percent=20.0,
    )
    _pinfo = types.SimpleNamespace(rss=100 * 1024**2)
    _proc = types.SimpleNamespace(memory_info=lambda: _pinfo)

    psutil_stub = types.SimpleNamespace(
        cpu_percent=lambda interval=None: 12.3,
        cpu_count=lambda logical=True: 8,
        virtual_memory=lambda: _vmem,
        disk_usage=lambda path="/": _disk,
        boot_time=lambda: time.time() - 3600,
        sensors_temperatures=lambda: {},
        sensors_battery=lambda: types.SimpleNamespace(percent=77.0, power_plugged=True),
        Process=lambda pid=None: _proc,
        getloadavg=lambda: (0.1, 0.1, 0.1),  # на случай, если вызывается
    )
    sys.modules["psutil"] = psutil_stub
# --- end psutil stub ---

"""Настройки тестов для торгового бота."""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock
import pandas as pd

# Путь к корню проекта чтобы импорты работали одинаково локально и в CI
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture
def sample_ohlcv():
    """Мини-набор OHLCV для быстрых тестов"""
    return pd.DataFrame({
        'open': [50000, 50100, 50200, 50150, 50300],
        'high': [50200, 50300, 50400, 50350, 50500],
        'low': [49800, 49900, 50000, 49950, 50100],
        'close': [50100, 50200, 50150, 50300, 50400],
        'volume': [100, 120, 110, 130, 140]
    })

@pytest.fixture
def mock_exchange():
    """Мок биржи для безопасного тестирования"""
    exchange = Mock()
    exchange.get_last_price.return_value = 50000.0
    exchange.fetch_ohlcv.return_value = [
        [1640995200000, 50000, 50200, 49800, 50100, 100],
        [1640995260000, 50100, 50300, 49900, 50200, 120]
    ]
    exchange.create_market_buy_order.return_value = {
        'id': 'test_123', 'status': 'closed'
    }
    exchange.create_market_sell_order.return_value = {
        'id': 'sell_123', 'status': 'closed'
    }
    exchange.market_min_cost.return_value = 5.0
    exchange.round_amount.side_effect = lambda symbol, amt: round(float(amt), 8)
    return exchange

@pytest.fixture
def mock_state():
    """Простой мок StateManager"""
    state = Mock()
    state.get.return_value = False
    state.is_position_active.return_value = False
    state.set.side_effect = lambda *args, **kwargs: None
    return state
