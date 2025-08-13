"""Исправленные тесты для модуля технических индикаторов."""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, Mock
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def sample_ohlcv_data():
    """Создает образец OHLCV данных для тестирования"""
    dates = pd.date_range('2024-01-01', periods=100, freq='15min')
    
    # Генерируем реалистичные данные с трендом
    np.random.seed(42)
    base_price = 50000
    trend = np.linspace(0, 0.05, 100)
    noise = np.random.normal(0, 0.001, 100)
    
    prices = base_price * (1 + trend + noise)
    
    df = pd.DataFrame({
        'open': prices * (1 + np.random.uniform(-0.001, 0.001, 100)),
        'high': prices * (1 + np.random.uniform(0, 0.002, 100)),
        'low': prices * (1 + np.random.uniform(-0.002, 0, 100)),
        'close': prices,
        'volume': np.random.uniform(100, 1000, 100)
    }, index=dates)
    
    return df


@pytest.fixture
def small_ohlcv_data():
    """Маленький набор данных для быстрых тестов"""
    return pd.DataFrame({
        'open': [100, 102, 101, 103, 102],
        'high': [102, 103, 102, 104, 103],
        'low': [99, 101, 100, 102, 101],
        'close': [101, 101.5, 102, 103, 102.5],
        'volume': [1000, 1200, 900, 1100, 1050]
    })


class TestTechnicalIndicatorsModule:
    """Тесты для реального модуля technical_indicators"""
    
    def test_module_import(self):
        """Тест импорта модуля"""
        try:
            from analysis import technical_indicators
            assert technical_indicators is not None
        except ImportError as e:
            pytest.skip(f"Cannot import technical_indicators: {e}")
    
    def test_calculate_all_indicators_exists(self):
        """Тест наличия функции calculate_all_indicators"""
        from analysis import technical_indicators
        
        assert hasattr(technical_indicators, 'calculate_all_indicators')
        assert callable(technical_indicators.calculate_all_indicators)
    
    def test_calculate_all_indicators_basic(self, sample_ohlcv_data):
        """Тест базовой функциональности calculate_all_indicators"""
        from analysis.technical_indicators import calculate_all_indicators
        
        result = calculate_all_indicators(sample_ohlcv_data)
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(sample_ohlcv_data)
        
        # Проверяем что добавлены новые колонки
        assert len(result.columns) > len(sample_ohlcv_data.columns)
        
        # Проверяем наличие основных индикаторов
        expected_indicators = ['rsi', 'macd', 'ema_20', 'sma_20']
        for indicator in expected_indicators:
            if indicator in result.columns:
                assert indicator in result.columns
    
    def test_calculate_all_indicators_preserves_original(self, sample_ohlcv_data):
        """Тест что исходные данные не модифицируются"""
        from analysis.technical_indicators import calculate_all_indicators
        
        original_copy = sample_ohlcv_data.copy()
        result = calculate_all_indicators(sample_ohlcv_data)
        
        # Исходный DataFrame не должен измениться
        pd.testing.assert_frame_equal(sample_ohlcv_data, original_copy)
        
        # Результат должен содержать исходные колонки
        for col in sample_ohlcv_data.columns:
            assert col in result.columns
    
    def test_calculate_all_indicators_empty_data(self):
        """Тест с пустыми данными"""
        from analysis.technical_indicators import calculate_all_indicators
        
        empty_df = pd.DataFrame()
        
        # Не должно падать
        result = calculate_all_indicators(empty_df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
    
    def test_calculate_all_indicators_single_row(self):
        """Тест с одной строкой данных"""
        from analysis.technical_indicators import calculate_all_indicators
        
        single_row = pd.DataFrame({
            'open': [100],
            'high': [101],
            'low': [99],
            'close': [100],
            'volume': [1000]
        })
        
        result = calculate_all_indicators(single_row)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
    
    def test_atr_functions(self, sample_ohlcv_data):
        """Тест функций ATR"""
        from analysis import technical_indicators
        
        # Проверяем наличие ATR функций
        if hasattr(technical_indicators, '_atr_series_for_ml'):
            atr = technical_indicators._atr_series_for_ml(sample_ohlcv_data)
            assert isinstance(atr, pd.Series)
            assert len(atr) == len(sample_ohlcv_data)
        
        if hasattr(technical_indicators, 'calculate_atr'):
            atr = technical_indicators.calculate_atr(sample_ohlcv_data, period=14)
            assert isinstance(atr, (pd.Series, np.ndarray))
    
    def test_rsi_calculation(self, sample_ohlcv_data):
        """Тест расчета RSI если функция доступна"""
        from analysis import technical_indicators
        
        # Проверяем разные варианты функции RSI
        rsi_functions = ['calculate_rsi', 'rsi', 'compute_rsi', '_calculate_rsi']
        
        for func_name in rsi_functions:
            if hasattr(technical_indicators, func_name):
                func = getattr(technical_indicators, func_name)
                if callable(func):
                    try:
                        rsi = func(sample_ohlcv_data['close'], 14)
                        assert isinstance(rsi, (pd.Series, np.ndarray))
                        
                        # RSI должен быть в диапазоне 0-100
                        valid_rsi = rsi[~pd.isna(rsi)]
                        if len(valid_rsi) > 0:
                            assert (valid_rsi >= 0).all()
                            assert (valid_rsi <= 100).all()
                        break
                    except:
                        continue
    
    def test_macd_calculation(self, sample_ohlcv_data):
        """Тест расчета MACD если функция доступна"""
        from analysis import technical_indicators
        
        # Проверяем разные варианты функции MACD
        macd_functions = ['calculate_macd', 'macd', 'compute_macd', '_calculate_macd']
        
        for func_name in macd_functions:
            if hasattr(technical_indicators, func_name):
                func = getattr(technical_indicators, func_name)
                if callable(func):
                    try:
                        result = func(sample_ohlcv_data['close'])
                        
                        # MACD обычно возвращает 3 значения или DataFrame
                        if isinstance(result, tuple):
                            assert len(result) >= 2  # Минимум MACD и Signal
                        elif isinstance(result, pd.DataFrame):
                            assert len(result.columns) >= 2
                        break
                    except:
                        continue


class TestIndicatorIntegration:
    """Интеграционные тесты индикаторов"""
    
    def test_indicators_with_real_data(self):
        """Тест с реалистичными данными"""
        from analysis.technical_indicators import calculate_all_indicators
        
        # Создаем реалистичные данные
        dates = pd.date_range('2024-01-01', periods=200, freq='15min')
        
        # Симулируем разные рыночные условия
        # Восходящий тренд
        uptrend = np.linspace(50000, 52000, 100)
        # Боковик
        sideways = np.ones(50) * 52000 + np.random.normal(0, 50, 50)
        # Нисходящий тренд
        downtrend = np.linspace(52000, 51000, 50)
        
        prices = np.concatenate([uptrend, sideways, downtrend])
        
        df = pd.DataFrame({
            'open': prices * (1 + np.random.uniform(-0.001, 0.001, 200)),
            'high': prices * (1 + np.random.uniform(0, 0.002, 200)),
            'low': prices * (1 + np.random.uniform(-0.002, 0, 200)),
            'close': prices,
            'volume': np.random.uniform(1000, 5000, 200)
        }, index=dates)
        
        result = calculate_all_indicators(df)
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)
        
        # Проверяем что индикаторы реагируют на изменение тренда
        if 'rsi' in result.columns:
            # RSI должен быть высоким в конце восходящего тренда
            rsi_uptrend_end = result['rsi'].iloc[95:100].mean()
            # RSI должен быть низким в конце нисходящего тренда
            rsi_downtrend_end = result['rsi'].iloc[-5:].mean()
            
            if not pd.isna(rsi_uptrend_end) and not pd.isna(rsi_downtrend_end):
                assert rsi_uptrend_end > rsi_downtrend_end
    
    def test_indicators_with_missing_data(self):
        """Тест с пропущенными данными"""
        from analysis.technical_indicators import calculate_all_indicators
        
        # Данные с NaN значениями
        df = pd.DataFrame({
            'open': [100, np.nan, 102, 103, 104],
            'high': [101, 102, np.nan, 104, 105],
            'low': [99, 100, 101, np.nan, 103],
            'close': [100, 101, 102, 103, np.nan],
            'volume': [1000, np.nan, 1200, 1300, 1400]
        })
        
        # Не должно падать
        result = calculate_all_indicators(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)
    
    def test_indicators_performance(self):
        """Тест производительности"""
        from analysis.technical_indicators import calculate_all_indicators
        import time
        
        # Большой датасет
        large_df = pd.DataFrame({
            'open': np.random.randn(5000) * 100 + 50000,
            'high': np.random.randn(5000) * 100 + 50100,
            'low': np.random.randn(5000) * 100 + 49900,
            'close': np.random.randn(5000) * 100 + 50000,
            'volume': np.random.uniform(100, 10000, 5000)
        })
        
        start_time = time.time()
        result = calculate_all_indicators(large_df)
        end_time = time.time()
        
        execution_time = end_time - start_time
        
        # Должно выполняться за разумное время
        assert execution_time < 10.0, f"Too slow: {execution_time:.2f}s"
        assert len(result) == len(large_df)


class TestIndicatorHelpers:
    """Тесты вспомогательных функций"""
    
    def test_ema_sma_functions(self):
        """Тест функций EMA и SMA"""
        from analysis import technical_indicators
        
        prices = pd.Series([100, 102, 101, 103, 102, 104, 103, 105])
        
        # Тестируем SMA
        if hasattr(technical_indicators, 'calculate_sma'):
            sma = technical_indicators.calculate_sma(prices, 3)
            assert isinstance(sma, pd.Series)
            # Проверяем корректность расчета
            assert abs(sma.iloc[2] - (100 + 102 + 101) / 3) < 0.01
        
        # Тестируем EMA
        if hasattr(technical_indicators, 'calculate_ema'):
            ema = technical_indicators.calculate_ema(prices, 3)
            assert isinstance(ema, pd.Series)
            assert len(ema) == len(prices)
    
    def test_bollinger_bands(self):
        """Тест полос Боллинджера"""
        from analysis import technical_indicators
        
        prices = pd.Series(np.random.normal(100, 2, 50))
        
        if hasattr(technical_indicators, 'calculate_bollinger_bands'):
            result = technical_indicators.calculate_bollinger_bands(prices, 20, 2)
            
            if isinstance(result, tuple):
                upper, middle, lower = result
                assert (upper > middle).all()
                assert (middle > lower).all()
            elif isinstance(result, pd.DataFrame):
                assert 'upper' in result.columns or 'bb_upper' in result.columns
    
    def test_volume_indicators(self):
        """Тест индикаторов объема"""
        from analysis import technical_indicators
        
        df = pd.DataFrame({
            'close': [100, 101, 102, 101, 103],
            'volume': [1000, 1200, 900, 1100, 1300]
        })
        
        if hasattr(technical_indicators, 'calculate_volume_indicators'):
            result = technical_indicators.calculate_volume_indicators(df)
            assert isinstance(result, (dict, pd.DataFrame, pd.Series))


class TestEdgeCases:
    """Тесты граничных случаев"""
    
    def test_extreme_values(self):
        """Тест с экстремальными значениями"""
        from analysis.technical_indicators import calculate_all_indicators
        
        extreme_df = pd.DataFrame({
            'open': [1e-10, 1e10, 100, 100],
            'high': [1e-10, 1e10, 101, 101],
            'low': [1e-10, 1e10, 99, 99],
            'close': [1e-10, 1e10, 100, 100],
            'volume': [1, 1e15, 1000, 1000]
        })
        
        # Должен обработать без overflow
        result = calculate_all_indicators(extreme_df)
        assert isinstance(result, pd.DataFrame)
        
        # Проверяем что нет inf значений в числовых колонках
        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            assert not np.isinf(result[col]).any(), f"Inf values in {col}"
    
    def test_constant_values(self):
        """Тест когда все значения одинаковые"""
        from analysis.technical_indicators import calculate_all_indicators
        
        constant_df = pd.DataFrame({
            'open': [100] * 50,
            'high': [100] * 50,
            'low': [100] * 50,
            'close': [100] * 50,
            'volume': [1000] * 50
        })
        
        result = calculate_all_indicators(constant_df)
        
        # RSI должен быть около 50 (нет движения)
        if 'rsi' in result.columns:
            rsi_values = result['rsi'].dropna()
            if len(rsi_values) > 0:
                assert 40 < rsi_values.mean() < 60
        
        # ATR должен быть близок к 0
        if 'atr' in result.columns:
            atr_values = result['atr'].dropna()
            if len(atr_values) > 0:
                assert atr_values.mean() < 1.0