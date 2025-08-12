import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch
from analysis.market_analyzer import MultiTimeframeAnalyzer
from config.settings import MarketCondition


@pytest.fixture
def sample_market_data():
    """Создает образцы рыночных данных для тестирования"""
    dates_1d = pd.date_range('2024-01-01', periods=50, freq='D')
    dates_4h = pd.date_range('2024-01-01', periods=200, freq='4h')
    
    # Создаем трендовые данные (восходящий тренд)
    base_price = 50000
    trend_1d = np.linspace(0, 0.2, 50)  # 20% рост за период
    trend_4h = np.linspace(0, 0.2, 200)
    
    # Добавляем шум
    noise_1d = np.random.normal(0, 0.02, 50)
    noise_4h = np.random.normal(0, 0.01, 200)
    
    df_1d = pd.DataFrame({
        'open': base_price * (1 + trend_1d + noise_1d),
        'high': base_price * (1 + trend_1d + noise_1d + 0.01),
        'low': base_price * (1 + trend_1d + noise_1d - 0.01),
        'close': base_price * (1 + trend_1d + noise_1d),
        'volume': np.random.uniform(1000, 5000, 50)
    }, index=dates_1d)
    
    df_4h = pd.DataFrame({
        'open': base_price * (1 + trend_4h + noise_4h),
        'high': base_price * (1 + trend_4h + noise_4h + 0.005),
        'low': base_price * (1 + trend_4h + noise_4h - 0.005),
        'close': base_price * (1 + trend_4h + noise_4h),
        'volume': np.random.uniform(200, 1000, 200)
    }, index=dates_4h)
    
    return df_1d, df_4h


@pytest.fixture
def sideways_market_data():
    """Создает данные бокового движения"""
    dates = pd.date_range('2024-01-01', periods=50, freq='D')
    base_price = 50000
    noise = np.random.normal(0, 0.005, 50)  # Малый шум
    
    df = pd.DataFrame({
        'open': base_price * (1 + noise),
        'high': base_price * (1 + noise + 0.003),
        'low': base_price * (1 + noise - 0.003),
        'close': base_price * (1 + noise),
        'volume': np.random.uniform(1000, 3000, 50)
    }, index=dates)
    
    return df, df.copy()  # Возвращаем одинаковые данные для 1D и 4H


@pytest.fixture
def analyzer():
    """Создает экземпляр анализатора"""
    return MultiTimeframeAnalyzer()


class TestMultiTimeframeAnalyzer:
    
    def test_analyzer_initialization(self, analyzer):
        """Тестирует инициализацию анализатора"""
        assert analyzer._w_daily == 0.6
        assert analyzer._w_h4 == 0.4
        assert analyzer._ema_fast == 20
        assert analyzer._ema_slow == 50
        assert analyzer._momentum_lookback == 20
        assert analyzer._vol_window == 60
        assert analyzer._atr_period == 14
    
    def test_analyze_market_condition_bull(self, analyzer, sample_market_data):
        """Тестирует анализ бычьего рынка"""
        df_1d, df_4h = sample_market_data
        
        condition, confidence = analyzer.analyze_market_condition(df_1d, df_4h)
        
        # Проверяем что определился бычий тренд
        assert condition in [MarketCondition.WEAK_BULL, MarketCondition.STRONG_BULL]
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.1  # Должна быть некоторая уверенность
    
    def test_analyze_market_condition_sideways(self, analyzer, sideways_market_data):
        """Тестирует анализ бокового рынка"""
        df_1d, df_4h = sideways_market_data
        
        condition, confidence = analyzer.analyze_market_condition(df_1d, df_4h)
        
        # Боковой рынок должен определяться как SIDEWAYS
        assert condition == MarketCondition.SIDEWAYS
        assert 0.0 <= confidence <= 1.0
    
    def test_analyze_empty_data(self, analyzer):
        """Тестирует поведение с пустыми данными"""
        empty_df = pd.DataFrame()
        
        condition, confidence = analyzer.analyze_market_condition(empty_df, empty_df)
        
        assert condition == MarketCondition.SIDEWAYS
        assert confidence == 0.10
    
    def test_analyze_invalid_data(self, analyzer):
        """Тестирует поведение с некорректными данными"""
        # DataFrame без нужных колонок
        bad_df = pd.DataFrame({'wrong_col': [1, 2, 3]})
        
        condition, confidence = analyzer.analyze_market_condition(bad_df, bad_df)
        
        assert condition == MarketCondition.SIDEWAYS
        assert confidence == 0.10
    
    def test_trend_calculation(self, analyzer, sample_market_data):
        """Тестирует расчет тренда"""
        df_1d, _ = sample_market_data
        
        trend = analyzer._trend(df_1d)
        
        assert isinstance(trend, float)
        assert -1.0 <= trend <= 1.0
        # Для восходящих данных тренд должен быть положительным
        assert trend > 0
    
    def test_trend_empty_data(self, analyzer):
        """Тестирует расчет тренда с пустыми данными"""
        empty_df = pd.DataFrame()
        
        trend = analyzer._trend(empty_df)
        
        assert trend == 0.0
    
    def test_strength_calculation(self, analyzer, sample_market_data):
        """Тестирует расчет силы тренда"""
        df_1d, _ = sample_market_data
        
        strength = analyzer._strength(df_1d)
        
        assert isinstance(strength, float)
        assert 0.0 <= strength <= 1.0
    
    @patch('analysis.technical_indicators._atr_series_for_ml')
    def test_strength_with_unified_atr(self, mock_atr, analyzer, sample_market_data):
        """Тестирует расчет силы с unified ATR"""
        df_1d, _ = sample_market_data
        
        # Мокаем unified ATR
        mock_atr_series = pd.Series([100.0] * len(df_1d), index=df_1d.index)
        mock_atr.return_value = mock_atr_series
        
        strength = analyzer._strength(df_1d)
        
        assert isinstance(strength, float)
        assert 0.0 <= strength <= 1.0
        mock_atr.assert_called_once()
    
    @patch('analysis.technical_indicators._atr_series_for_ml')
    def test_strength_atr_fallback(self, mock_atr, analyzer, sample_market_data):
        """Тестирует fallback при ошибке unified ATR"""
        df_1d, _ = sample_market_data
        
        # Мокаем исключение в unified ATR
        mock_atr.side_effect = Exception("ATR calculation failed")
        
        strength = analyzer._strength(df_1d)
        
        # Должен использовать fallback
        assert isinstance(strength, float)
        assert 0.0 <= strength <= 1.0
    
    def test_classify_conditions(self, analyzer):
        """Тестирует классификацию рыночных условий"""
        # Сильный бык
        condition = analyzer._classify(0.15, 0.8)
        assert condition == MarketCondition.STRONG_BULL
        
        # Слабый бык
        condition = analyzer._classify(0.07, 0.6)
        assert condition == MarketCondition.WEAK_BULL
        
        # Сильный медведь
        condition = analyzer._classify(-0.15, 0.8)
        assert condition == MarketCondition.STRONG_BEAR
        
        # Слабый медведь
        condition = analyzer._classify(-0.07, 0.6)
        assert condition == MarketCondition.WEAK_BEAR
        
        # Боковик
        condition = analyzer._classify(0.02, 0.4)
        assert condition == MarketCondition.SIDEWAYS
    
    def test_get_diagnostics(self, analyzer, sample_market_data):
        """Тестирует диагностические методы"""
        df_1d, df_4h = sample_market_data
        
        diagnostics = analyzer.get_diagnostics(df_1d, df_4h)
        
        # Проверяем структуру диагностики
        assert 'timeframes' in diagnostics
        assert 'combined' in diagnostics
        assert 'weights' in diagnostics
        assert 'parameters' in diagnostics
        
        # Проверяем данные по таймфреймам
        assert '1d' in diagnostics['timeframes']
        assert '4h' in diagnostics['timeframes']
        
        # Проверяем комбинированные данные
        combined = diagnostics['combined']
        assert 'trend' in combined
        assert 'strength' in combined
        assert 'condition' in combined
        assert 'confidence' in combined
        
        # Проверяем веса
        weights = diagnostics['weights']
        assert weights['daily'] == 0.6
        assert weights['4h'] == 0.4
    
    def test_get_diagnostics_error_handling(self, analyzer):
        """Тестирует обработку ошибок в диагностике"""
        # Передаем None данные
        diagnostics = analyzer.get_diagnostics(None, None)
        
        assert 'error' in diagnostics
    
    def test_validate_data_quality_good_data(self, analyzer, sample_market_data):
        """Тестирует валидацию качественных данных"""
        df_1d, df_4h = sample_market_data
        
        validation = analyzer.validate_data_quality(df_1d, df_4h)
        
        assert validation['valid'] is True
        assert len(validation['issues']) == 0
        assert 'data_quality' in validation
        assert validation['data_quality']['1d_rows'] == len(df_1d)
        assert validation['data_quality']['4h_rows'] == len(df_4h)
    
    def test_validate_data_quality_empty_data(self, analyzer):
        """Тестирует валидацию пустых данных"""
        empty_df = pd.DataFrame()
        
        validation = analyzer.validate_data_quality(empty_df, empty_df)
        
        assert validation['valid'] is False
        assert len(validation['issues']) > 0
        assert any('empty' in issue.lower() for issue in validation['issues'])
    
    def test_validate_data_quality_missing_columns(self, analyzer):
        """Тестирует валидацию данных с отсутствующими колонками"""
        bad_df = pd.DataFrame({'only_close': [1, 2, 3, 4, 5]})
        
        validation = analyzer.validate_data_quality(bad_df, bad_df)
        
        assert validation['valid'] is False
        assert any('missing columns' in issue.lower() for issue in validation['issues'])
    
    def test_validate_data_quality_insufficient_rows(self, analyzer):
        """Тестирует валидацию данных с недостаточным количеством строк"""
        # Создаем данные с малым количеством строк
        small_df = pd.DataFrame({
            'open': [1, 2],
            'high': [1.1, 2.1],
            'low': [0.9, 1.9],
            'close': [1.05, 2.05],
            'volume': [100, 200]
        })
        
        validation = analyzer.validate_data_quality(small_df, small_df)
        
        # Может быть валидным, но должны быть предупреждения
        assert len(validation['warnings']) > 0
        assert any('rows' in warning.lower() for warning in validation['warnings'])
    
    def test_get_configuration(self, analyzer):
        """Тестирует получение конфигурации"""
        config = analyzer.get_configuration()
        
        assert 'timeframe_weights' in config
        assert 'ema_parameters' in config
        assert 'analysis_parameters' in config
        assert 'classification_thresholds' in config
        
        # Проверяем корректность значений
        assert config['timeframe_weights']['daily'] == 0.6
        assert config['ema_parameters']['fast'] == 20
        assert config['analysis_parameters']['atr_period'] == 14
    
    def test_update_configuration(self, analyzer):
        """Тестирует обновление конфигурации"""
        # Обновляем несколько параметров
        updated = analyzer.update_configuration(
            w_daily=0.7,
            ema_fast=15,
            atr_period=21
        )
        
        assert 'w_daily' in updated
        assert 'ema_fast' in updated
        assert 'atr_period' in updated
        
        # Проверяем что значения действительно обновились
        assert analyzer._w_daily == 0.7
        assert analyzer._ema_fast == 15
        assert analyzer._atr_period == 21
    
    def test_update_configuration_invalid_params(self, analyzer):
        """Тестирует обновление с невалидными параметрами"""
        updated = analyzer.update_configuration(
            invalid_param=123,
            another_invalid=456
        )
        
        assert len(updated) == 0  # Ничего не должно обновиться
    
    def test_with_nan_data(self, analyzer):
        """Тестирует работу с данными содержащими NaN"""
        # Создаем данные с NaN
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        df_with_nan = pd.DataFrame({
            'open': [50000] * 30,
            'high': [50100] * 30,
            'low': [49900] * 30,
            'close': [50000] * 30,
            'volume': [1000] * 30
        }, index=dates)
        
        # Добавляем NaN в несколько мест
        df_with_nan.loc[df_with_nan.index[5], 'close'] = np.nan
        df_with_nan.loc[df_with_nan.index[10], 'volume'] = np.nan
        
        condition, confidence = analyzer.analyze_market_condition(df_with_nan, df_with_nan)
        
        # Должен обработать NaN без ошибок
        assert isinstance(condition, MarketCondition)
        assert 0.0 <= confidence <= 1.0
    
    def test_extreme_values(self, analyzer):
        """Тестирует работу с экстремальными значениями"""
        # Создаем данные с очень большими изменениями
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        prices = [50000 * (1.1 ** i) for i in range(30)]  # Экспоненциальный рост
        
        df_extreme = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [1000] * 30
        }, index=dates)
        
        condition, confidence = analyzer.analyze_market_condition(df_extreme, df_extreme)
        
        # Должен определить сильный бычий тренд
        assert condition in [MarketCondition.WEAK_BULL, MarketCondition.STRONG_BULL]
        assert confidence > 0.3  # Высокая уверенность для такого тренда


class TestEdgeCases:
    """Тесты граничных случаев"""
    
    def test_single_row_data(self):
        """Тестирует данные с одной строкой"""
        analyzer = MultiTimeframeAnalyzer()
        
        single_row = pd.DataFrame({
            'open': [50000],
            'high': [50100],
            'low': [49900],
            'close': [50000],
            'volume': [1000]
        })
        
        condition, confidence = analyzer.analyze_market_condition(single_row, single_row)
        
        assert condition == MarketCondition.SIDEWAYS
        assert confidence >= 0.0
    
    def test_zero_volume_data(self):
        """Тестирует данные с нулевым объемом"""
        analyzer = MultiTimeframeAnalyzer()
        
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        zero_volume_df = pd.DataFrame({
            'open': [50000] * 30,
            'high': [50100] * 30,
            'low': [49900] * 30,
            'close': [50000] * 30,
            'volume': [0] * 30  # Нулевой объем
        }, index=dates)
        
        condition, confidence = analyzer.analyze_market_condition(zero_volume_df, zero_volume_df)
        
        # Должен обработать без ошибок
        assert isinstance(condition, MarketCondition)
        assert 0.0 <= confidence <= 1.0