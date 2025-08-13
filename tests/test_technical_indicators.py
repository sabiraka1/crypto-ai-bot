"""Комплексные тесты для модуля технических индикаторов."""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, Mock
from analysis.technical_indicators import (
    calculate_rsi, calculate_macd, calculate_bollinger_bands,
    calculate_ema, calculate_sma, calculate_stochastic,
    calculate_atr, calculate_adx, calculate_volume_indicators,
    calculate_all_indicators, detect_patterns, calculate_pivots
)


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


class TestBasicIndicators:
    """Тесты базовых индикаторов"""
    
    def test_calculate_sma(self, sample_ohlcv_data):
        """Тест простой скользящей средней"""
        period = 20
        sma = calculate_sma(sample_ohlcv_data['close'], period)
        
        assert isinstance(sma, pd.Series)
        assert len(sma) == len(sample_ohlcv_data)
        
        # Первые period-1 значений должны быть NaN
        assert sma.iloc[:period-1].isna().all()
        
        # Остальные значения должны быть числами
        assert sma.iloc[period-1:].notna().all()
        
        # Проверяем корректность расчета
        manual_sma = sample_ohlcv_data['close'].rolling(period).mean()
        pd.testing.assert_series_equal(sma, manual_sma, check_names=False)
    
    def test_calculate_ema(self, sample_ohlcv_data):
        """Тест экспоненциальной скользящей средней"""
        period = 20
        ema = calculate_ema(sample_ohlcv_data['close'], period)
        
        assert isinstance(ema, pd.Series)
        assert len(ema) == len(sample_ohlcv_data)
        
        # EMA должна быть ближе к последним значениям чем SMA
        sma = calculate_sma(sample_ohlcv_data['close'], period)
        last_price = sample_ohlcv_data['close'].iloc[-1]
        
        # В восходящем тренде EMA > SMA
        if sample_ohlcv_data['close'].iloc[-1] > sample_ohlcv_data['close'].iloc[0]:
            assert ema.iloc[-1] > sma.iloc[-1]
    
    def test_calculate_rsi(self, sample_ohlcv_data):
        """Тест индекса относительной силы (RSI)"""
        period = 14
        rsi = calculate_rsi(sample_ohlcv_data['close'], period)
        
        assert isinstance(rsi, pd.Series)
        assert len(rsi) == len(sample_ohlcv_data)
        
        # RSI должен быть в диапазоне 0-100
        valid_rsi = rsi[rsi.notna()]
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()
        
        # Проверяем экстремальные значения
        # При сильном росте RSI должен быть высоким
        strong_uptrend = pd.Series([100 + i for i in range(20)])
        rsi_up = calculate_rsi(strong_uptrend, 14)
        assert rsi_up.iloc[-1] > 70  # Перекупленность
        
        # При сильном падении RSI должен быть низким
        strong_downtrend = pd.Series([100 - i for i in range(20)])
        rsi_down = calculate_rsi(strong_downtrend, 14)
        assert rsi_down.iloc[-1] < 30  # Перепроданность
    
    def test_calculate_macd(self, sample_ohlcv_data):
        """Тест MACD индикатора"""
        macd_line, signal_line, histogram = calculate_macd(
            sample_ohlcv_data['close'],
            fast_period=12,
            slow_period=26,
            signal_period=9
        )
        
        assert isinstance(macd_line, pd.Series)
        assert isinstance(signal_line, pd.Series)
        assert isinstance(histogram, pd.Series)
        
        # Все серии должны быть одинаковой длины
        assert len(macd_line) == len(sample_ohlcv_data)
        assert len(signal_line) == len(sample_ohlcv_data)
        assert len(histogram) == len(sample_ohlcv_data)
        
        # Гистограмма = MACD - Signal
        expected_hist = macd_line - signal_line
        pd.testing.assert_series_equal(
            histogram[histogram.notna()],
            expected_hist[expected_hist.notna()],
            check_names=False
        )
    
    def test_calculate_bollinger_bands(self, sample_ohlcv_data):
        """Тест полос Боллинджера"""
        period = 20
        std_dev = 2
        
        upper, middle, lower = calculate_bollinger_bands(
            sample_ohlcv_data['close'],
            period=period,
            std_dev=std_dev
        )
        
        assert isinstance(upper, pd.Series)
        assert isinstance(middle, pd.Series)
        assert isinstance(lower, pd.Series)
        
        # Проверяем отношения между полосами
        valid_idx = upper.notna()
        assert (upper[valid_idx] > middle[valid_idx]).all()
        assert (middle[valid_idx] > lower[valid_idx]).all()
        
        # Middle должна быть равна SMA
        sma = calculate_sma(sample_ohlcv_data['close'], period)
        pd.testing.assert_series_equal(middle, sma, check_names=False)
        
        # Ширина полос должна зависеть от волатильности
        volatility = sample_ohlcv_data['close'].rolling(period).std()
        band_width = upper - lower
        correlation = band_width.corr(volatility)
        assert correlation > 0.9  # Высокая корреляция с волатильностью
    
    def test_calculate_stochastic(self, sample_ohlcv_data):
        """Тест стохастического осциллятора"""
        k_period = 14
        d_period = 3
        
        k_line, d_line = calculate_stochastic(
            sample_ohlcv_data,
            k_period=k_period,
            d_period=d_period
        )
        
        assert isinstance(k_line, pd.Series)
        assert isinstance(d_line, pd.Series)
        
        # Значения должны быть в диапазоне 0-100
        valid_k = k_line[k_line.notna()]
        valid_d = d_line[d_line.notna()]
        
        assert (valid_k >= 0).all()
        assert (valid_k <= 100).all()
        assert (valid_d >= 0).all()
        assert (valid_d <= 100).all()
        
        # D-линия должна быть сглаженной версией K-линии
        # (менее волатильной)
        k_volatility = k_line.diff().abs().mean()
        d_volatility = d_line.diff().abs().mean()
        assert d_volatility < k_volatility


class TestVolatilityIndicators:
    """Тесты индикаторов волатильности"""
    
    def test_calculate_atr(self, sample_ohlcv_data):
        """Тест Average True Range"""
        period = 14
        atr = calculate_atr(sample_ohlcv_data, period)
        
        assert isinstance(atr, pd.Series)
        assert len(atr) == len(sample_ohlcv_data)
        
        # ATR должен быть положительным
        valid_atr = atr[atr.notna()]
        assert (valid_atr > 0).all()
        
        # ATR должен увеличиваться при увеличении волатильности
        # Создаем данные с растущей волатильностью
        volatile_data = sample_ohlcv_data.copy()
        volatile_data.iloc[50:] *= 1.5  # Увеличиваем волатильность
        
        atr_normal = calculate_atr(sample_ohlcv_data[:50], period)
        atr_volatile = calculate_atr(volatile_data[50:], period)
        
        assert atr_volatile.mean() > atr_normal.mean()
    
    def test_calculate_adx(self, sample_ohlcv_data):
        """Тест Average Directional Index"""
        period = 14
        adx = calculate_adx(sample_ohlcv_data, period)
        
        assert isinstance(adx, pd.Series)
        assert len(adx) == len(sample_ohlcv_data)
        
        # ADX должен быть в диапазоне 0-100
        valid_adx = adx[adx.notna()]
        assert (valid_adx >= 0).all()
        assert (valid_adx <= 100).all()
        
        # В сильном тренде ADX должен быть высоким
        # Создаем данные с сильным трендом
        strong_trend = pd.DataFrame({
            'high': [100 + i*2 for i in range(50)],
            'low': [99 + i*2 for i in range(50)],
            'close': [100 + i*2 for i in range(50)]
        })
        
        adx_trend = calculate_adx(strong_trend, period)
        assert adx_trend.iloc[-1] > 25  # Сильный тренд
    
    def test_atr_unified_function(self, sample_ohlcv_data):
        """Тест унифицированной функции ATR"""
        # Импортируем private функцию если она существует
        from analysis.technical_indicators import _atr_series_for_ml
        
        atr = _atr_series_for_ml(sample_ohlcv_data, period=14)
        
        assert isinstance(atr, pd.Series)
        assert len(atr) == len(sample_ohlcv_data)
        
        # Проверяем что NaN заполнены
        assert atr.notna().all()


class TestVolumeIndicators:
    """Тесты индикаторов объема"""
    
    def test_calculate_volume_indicators(self, sample_ohlcv_data):
        """Тест индикаторов объема"""
        volume_indicators = calculate_volume_indicators(sample_ohlcv_data)
        
        assert isinstance(volume_indicators, dict)
        
        # Проверяем наличие ключевых индикаторов
        expected_keys = ['volume_sma', 'volume_ratio', 'obv', 'volume_rsi']
        for key in expected_keys:
            assert key in volume_indicators
            assert isinstance(volume_indicators[key], pd.Series)
        
        # Volume ratio должен показывать относительный объем
        vol_ratio = volume_indicators['volume_ratio']
        assert (vol_ratio > 0).all()
        
        # OBV должен накапливаться
        obv = volume_indicators['obv']
        assert len(obv) == len(sample_ohlcv_data)
    
    def test_on_balance_volume(self, small_ohlcv_data):
        """Тест On Balance Volume"""
        volume_ind = calculate_volume_indicators(small_ohlcv_data)
        obv = volume_ind['obv']
        
        # Проверяем логику OBV
        # Если close > prev_close, добавляем объем
        # Если close < prev_close, вычитаем объем
        
        manual_obv = [0]
        for i in range(1, len(small_ohlcv_data)):
            if small_ohlcv_data['close'].iloc[i] > small_ohlcv_data['close'].iloc[i-1]:
                manual_obv.append(manual_obv[-1] + small_ohlcv_data['volume'].iloc[i])
            elif small_ohlcv_data['close'].iloc[i] < small_ohlcv_data['close'].iloc[i-1]:
                manual_obv.append(manual_obv[-1] - small_ohlcv_data['volume'].iloc[i])
            else:
                manual_obv.append(manual_obv[-1])
        
        # Сравниваем с небольшим допуском
        np.testing.assert_array_almost_equal(
            obv.values,
            manual_obv,
            decimal=2
        )


class TestPatternDetection:
    """Тесты определения паттернов"""
    
    def test_detect_patterns_basic(self, sample_ohlcv_data):
        """Тест базового определения паттернов"""
        patterns = detect_patterns(sample_ohlcv_data)
        
        assert isinstance(patterns, dict)
        
        # Проверяем наличие основных паттернов
        pattern_types = ['support', 'resistance', 'trend', 'reversal']
        
        for pattern_type in pattern_types:
            assert pattern_type in patterns
    
    def test_support_resistance_levels(self, sample_ohlcv_data):
        """Тест определения уровней поддержки и сопротивления"""
        patterns = detect_patterns(sample_ohlcv_data)
        
        support = patterns.get('support', [])
        resistance = patterns.get('resistance', [])
        
        # Должны быть найдены некоторые уровни
        assert len(support) > 0 or len(resistance) > 0
        
        # Уровни сопротивления должны быть выше поддержки
        if support and resistance:
            assert max(resistance) > min(support)
    
    def test_trend_detection(self):
        """Тест определения тренда"""
        # Создаем явный восходящий тренд
        uptrend_data = pd.DataFrame({
            'open': [100 + i for i in range(50)],
            'high': [101 + i for i in range(50)],
            'low': [99 + i for i in range(50)],
            'close': [100 + i for i in range(50)],
            'volume': [1000] * 50
        })
        
        patterns = detect_patterns(uptrend_data)
        assert patterns['trend'] == 'bullish'
        
        # Создаем явный нисходящий тренд
        downtrend_data = pd.DataFrame({
            'open': [100 - i for i in range(50)],
            'high': [101 - i for i in range(50)],
            'low': [99 - i for i in range(50)],
            'close': [100 - i for i in range(50)],
            'volume': [1000] * 50
        })
        
        patterns = detect_patterns(downtrend_data)
        assert patterns['trend'] == 'bearish'
    
    def test_candlestick_patterns(self, sample_ohlcv_data):
        """Тест свечных паттернов"""
        # Создаем doji паттерн
        doji_data = pd.DataFrame({
            'open': [100],
            'high': [101],
            'low': [99],
            'close': [100.1],  # Почти равно open
            'volume': [1000]
        })
        
        patterns = detect_patterns(doji_data)
        candlesticks = patterns.get('candlestick_patterns', [])
        
        # Должен определить doji или похожий паттерн
        assert len(candlesticks) > 0 or 'doji' in str(candlesticks).lower()


class TestPivotPoints:
    """Тесты точек разворота"""
    
    def test_calculate_pivots(self, sample_ohlcv_data):
        """Тест расчета точек разворота"""
        pivots = calculate_pivots(sample_ohlcv_data)
        
        assert isinstance(pivots, dict)
        
        # Проверяем наличие всех уровней
        expected_levels = ['pivot', 'r1', 'r2', 'r3', 's1', 's2', 's3']
        for level in expected_levels:
            assert level in pivots
            assert isinstance(pivots[level], (int, float))
        
        # Проверяем правильный порядок уровней
        assert pivots['r3'] > pivots['r2'] > pivots['r1'] > pivots['pivot']
        assert pivots['pivot'] > pivots['s1'] > pivots['s2'] > pivots['s3']
    
    def test_pivots_calculation_formula(self):
        """Тест формулы расчета пивотов"""
        # Простые данные для проверки формулы
        data = pd.DataFrame({
            'high': [110],
            'low': [90],
            'close': [100],
            'open': [95],
            'volume': [1000]
        })
        
        pivots = calculate_pivots(data)
        
        # Классическая формула: P = (H + L + C) / 3
        expected_pivot = (110 + 90 + 100) / 3
        assert abs(pivots['pivot'] - expected_pivot) < 0.01
        
        # R1 = 2 * P - L
        expected_r1 = 2 * expected_pivot - 90
        assert abs(pivots['r1'] - expected_r1) < 0.01
        
        # S1 = 2 * P - H
        expected_s1 = 2 * expected_pivot - 110
        assert abs(pivots['s1'] - expected_s1) < 0.01


class TestAllIndicators:
    """Тесты функции calculate_all_indicators"""
    
    def test_calculate_all_indicators_completeness(self, sample_ohlcv_data):
        """Тест полноты расчета всех индикаторов"""
        df_with_indicators = calculate_all_indicators(sample_ohlcv_data)
        
        assert isinstance(df_with_indicators, pd.DataFrame)
        
        # Проверяем наличие основных индикаторов
        expected_indicators = [
            'rsi', 'macd', 'macd_signal', 'macd_hist',
            'ema_20', 'ema_50', 'sma_20', 'sma_50',
            'bb_upper', 'bb_middle', 'bb_lower',
            'stoch_k', 'stoch_d', 'atr', 'adx',
            'volume_sma', 'volume_ratio'
        ]
        
        for indicator in expected_indicators:
            assert indicator in df_with_indicators.columns, f"Missing {indicator}"
    
    def test_calculate_all_indicators_no_modification(self, sample_ohlcv_data):
        """Тест что исходные данные не модифицируются"""
        original_copy = sample_ohlcv_data.copy()
        df_with_indicators = calculate_all_indicators(sample_ohlcv_data)
        
        # Исходный DataFrame не должен измениться
        pd.testing.assert_frame_equal(sample_ohlcv_data, original_copy)
        
        # Результат должен содержать исходные колонки
        for col in sample_ohlcv_data.columns:
            assert col in df_with_indicators.columns
    
    def test_calculate_all_indicators_with_params(self, sample_ohlcv_data):
        """Тест с пользовательскими параметрами"""
        custom_params = {
            'rsi_period': 21,
            'ema_fast': 10,
            'ema_slow': 30,
            'bb_period': 30,
            'bb_std': 3
        }
        
        df_with_indicators = calculate_all_indicators(
            sample_ohlcv_data,
            **custom_params
        )
        
        # Проверяем что параметры применились
        # RSI с периодом 21 должен отличаться от стандартного
        df_standard = calculate_all_indicators(sample_ohlcv_data)
        
        # Значения должны отличаться
        assert not df_with_indicators['rsi'].equals(df_standard['rsi'])


class TestIndicatorEdgeCases:
    """Тесты граничных случаев"""
    
    def test_empty_dataframe(self):
        """Тест с пустым DataFrame"""
        empty_df = pd.DataFrame()
        
        # Функции не должны падать
        result = calculate_all_indicators(empty_df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
    
    def test_single_row_dataframe(self):
        """Тест с одной строкой данных"""
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
        
        # Большинство индикаторов должны быть NaN
        assert result.iloc[0].isna().sum() > 10
    
    def test_all_same_values(self):
        """Тест когда все значения одинаковые"""
        same_values = pd.DataFrame({
            'open': [100] * 50,
            'high': [100] * 50,
            'low': [100] * 50,
            'close': [100] * 50,
            'volume': [1000] * 50
        })
        
        result = calculate_all_indicators(same_values)
        
        # RSI должен быть около 50 (нет движения)
        rsi = result['rsi'].iloc[-1]
        if not pd.isna(rsi):
            assert 45 < rsi < 55
        
        # ATR должен быть близок к 0
        atr = result['atr'].iloc[-1]
        if not pd.isna(atr):
            assert atr < 0.1
    
    def test_missing_columns(self):
        """Тест с отсутствующими колонками"""
        incomplete_df = pd.DataFrame({
            'close': [100, 101, 102, 103],
            'volume': [1000, 1100, 1200, 1300]
        })
        
        # Должен обработать gracefully
        result = calculate_all_indicators(incomplete_df)
        assert isinstance(result, pd.DataFrame)
        
        # Индикаторы требующие OHLC должны быть NaN
        if 'atr' in result.columns:
            assert result['atr'].isna().all()
    
    def test_nan_values_handling(self):
        """Тест обработки NaN значений"""
        data_with_nan = pd.DataFrame({
            'open': [100, np.nan, 102, 103],
            'high': [101, 102, np.nan, 104],
            'low': [99, 100, 101, np.nan],
            'close': [100, 101, 102, 103],
            'volume': [1000, np.nan, 1200, 1300]
        })
        
        # Не должно падать
        result = calculate_all_indicators(data_with_nan)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(data_with_nan)
    
    def test_extreme_values(self):
        """Тест с экстремальными значениями"""
        extreme_data = pd.DataFrame({
            'open': [1e-10, 1e10, 100, 100],
            'high': [1e-10, 1e10, 101, 101],
            'low': [1e-10, 1e10, 99, 99],
            'close': [1e-10, 1e10, 100, 100],
            'volume': [1, 1e15, 1000, 1000]
        })
        
        # Должен обработать без overflow/underflow
        result = calculate_all_indicators(extreme_data)
        assert isinstance(result, pd.DataFrame)
        
        # Проверяем что нет inf значений
        assert not np.isinf(result.select_dtypes(include=[np.number])).any().any()


class TestPerformance:
    """Тесты производительности"""
    
    def test_large_dataset_performance(self):
        """Тест производительности на большом датасете"""
        import time
        
        # Создаем большой датасет
        large_data = pd.DataFrame({
            'open': np.random.randn(10000) * 100 + 50000,
            'high': np.random.randn(10000) * 100 + 50100,
            'low': np.random.randn(10000) * 100 + 49900,
            'close': np.random.randn(10000) * 100 + 50000,
            'volume': np.random.uniform(100, 10000, 10000)
        })
        
        # Замеряем время выполнения
        start_time = time.time()
        result = calculate_all_indicators(large_data)
        end_time = time.time()
        
        execution_time = end_time - start_time
        
        # Должно выполняться за разумное время (< 5 секунд)
        assert execution_time < 5.0, f"Too slow: {execution_time:.2f}s"
        
        # Результат должен быть корректным
        assert len(result) == len(large_data)
        assert len(result.columns) > len(large_data.columns)
    
    def test_memory_efficiency(self):
        """Тест эффективности использования памяти"""
        import sys
        
        # Средний датасет
        medium_data = pd.DataFrame({
            'open': np.random.randn(1000) * 100 + 50000,
            'high': np.random.randn(1000) * 100 + 50100,
            'low': np.random.randn(1000) * 100 + 49900,
            'close': np.random.randn(1000) * 100 + 50000,
            'volume': np.random.uniform(100, 10000, 1000)
        })
        
        # Проверяем что не создается слишком много копий
        initial_size = sys.getsizeof(medium_data)
        result = calculate_all_indicators(medium_data)
        result_size = sys.getsizeof(result)
        
        # Результат не должен быть слишком большим
        # (не более чем в 5 раз больше исходных данных)
        assert result_size < initial_size * 5