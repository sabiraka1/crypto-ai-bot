# conftest.py - РЕКОМЕНДУЕМЫЙ
"""Настройки тестов для торгового бота."""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock
import pandas as pd

# Путь к проекту
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture
def sample_ohlcv():
    """Реальные OHLCV данные для тестов"""
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
    exchange.market_min_cost.return_value = 5.0
    return exchange

@pytest.fixture
def mock_state():
    """Мок StateManager"""
    state = Mock()
    state.get.return_value = False
    state.is_position_active.return_value = False
    return state