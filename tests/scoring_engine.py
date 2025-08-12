import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from analysis.scoring_engine import ScoringEngine


@pytest.fixture
def sample_market_df():
    """Создает образец рыночных данных для тестирования"""
    dates = pd.date_range('2024-01-01', periods=100, freq='15min')
    
    # Создаем реалистичные OHLCV данные
    base_price = 50000
    trend = np.linspace(0, 0.05, 100)  # 5% рост
    noise = np.random.normal(0, 0.001, 100)
    
    prices = base_price * (1 + trend + noise)
    
    df = pd.DataFrame({
        'open': prices,
        'high': prices * 1.002,
        'low': prices * 0.998,
        'close': prices,
        'volume': np.random.uniform(100, 1000, 100)
    }, index=dates)
    
    return df


@pytest.fixture
def scoring_engine():
    """Создает экземпляр scoring engine"""
    return ScoringEngine()


@pytest.fixture
def mock_technical_indicators():
    """Мокает технические индикаторы"""
    return {
        'rsi': 65.0,
        'macd': 0.5,
        'macd_signal': 0.3,
        'macd_hist': 0.2,
        'ema_20': 50100.0,
        'ema_50': 50000.0,
        'sma_20': 50050.0,
        'bb_upper': 50200.0,
        'bb_lower': 49800.0,
        'bb_middle': 50000.0,
        'stoch_k': 70.0,
        'stoch_d': 68.0,
        'adx': 25.0,
        'volume_ratio': 1.2,
        'atr': 100.0
    }


class TestScoringEngine:
    
    def test_scoring_engine_initialization(self, scoring_engine):
        """Тестирует инициализацию scoring engine"""
        assert hasattr(scoring_engine, 'min_score_to_buy')
        assert hasattr(scoring_engine, 'evaluate')
        assert hasattr(scoring_engine, 'position_fraction')
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    def test_evaluate_basic_functionality(self, mock_calc_indicators, scoring_engine, sample_market_df, mock_technical_indicators):
        """Тестирует базовую функциональность evaluate"""
        # Мокаем результат calculate_all_indicators
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        # Вызываем evaluate
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.7)
        
        # Проверяем результат
        assert isinstance(result, tuple)
        assert len(result) >= 2
        
        buy_score, ai_score_result = result[0], result[1]
        assert isinstance(buy_score, (int, float))
        assert isinstance(ai_score_result, (int, float))
        assert 0.0 <= buy_score <= 1.0
        assert 0.0 <= ai_score_result <= 1.0
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    def test_evaluate_with_details(self, mock_calc_indicators, scoring_engine, sample_market_df, mock_technical_indicators):
        """Тестирует evaluate с возвращением деталей"""
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.7)
        
        if len(result) >= 3:
            buy_score, ai_score_result, details = result
            assert isinstance(details, dict)
        else:
            # Если детали не возвращаются, это тоже валидно
            assert len(result) == 2
    
    def test_evaluate_empty_dataframe(self, scoring_engine):
        """Тестирует поведение с пустым DataFrame"""
        empty_df = pd.DataFrame()
        
        result = scoring_engine.evaluate(empty_df, ai_score=0.5)
        
        # Должен вернуть дефолтные значения без ошибок
        assert isinstance(result, tuple)
        buy_score = result[0]
        assert isinstance(buy_score, (int, float))
        assert 0.0 <= buy_score <= 1.0
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    def test_evaluate_exception_handling(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """Тестирует обработку исключений в evaluate"""
        # Мокаем исключение
        mock_calc_indicators.side_effect = Exception("Calculation failed")
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.5)
        
        # Должен обработать исключение и вернуть результат
        assert isinstance(result, tuple)
        buy_score = result[0]
        assert isinstance(buy_score, (int, float))
    
    def test_position_fraction_basic(self, scoring_engine):
        """Тестирует базовую функциональность position_fraction"""
        # Тестируем разные значения AI score
        test_scores = [0.0, 0.3, 0.5, 0.7, 0.9, 1.0]
        
        for score in test_scores:
            fraction = scoring_engine.position_fraction(score)
            
            assert isinstance(fraction, (int, float))
            assert 0.0 <= fraction <= 1.0
            
            # Чем выше AI score, тем больше должна быть фракция
            if score >= 0.5:
                assert fraction > 0.0
    
    def test_position_fraction_progression(self, scoring_engine):
        """Тестирует что position_fraction монотонно возрастает"""
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        fractions = [scoring_engine.position_fraction(score) for score in scores]
        
        # Проверяем монотонность (не строгую, допускаем равенство)
        for i in range(1, len(fractions)):
            assert fractions[i] >= fractions[i-1], f"Fraction decreased: {fractions[i-1]} -> {fractions[i]}"
    
    def test_position_fraction_edge_cases(self, scoring_engine):
        """Тестирует граничные случаи для position_fraction"""
        # Отрицательные значения
        assert scoring_engine.position_fraction(-0.5) >= 0.0
        
        # Значения больше 1
        assert scoring_engine.position_fraction(1.5) <= 1.0
        
        # NaN
        result = scoring_engine.position_fraction(float('nan'))
        assert isinstance(result, (int, float))
        assert not np.isnan(result)
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    @patch('analysis.market_analyzer.MultiTimeframeAnalyzer')
    def test_evaluate_with_market_analyzer(self, mock_analyzer_class, mock_calc_indicators, 
                                         scoring_engine, sample_market_df, mock_technical_indicators):
        """Тестирует интеграцию с market analyzer"""
        # Мокаем технические индикаторы
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        # Мокаем market analyzer
        mock_analyzer = Mock()
        mock_analyzer.analyze_market_condition.return_value = ("bull", 0.8)
        mock_analyzer_class.return_value = mock_analyzer
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.7)
        
        assert isinstance(result, tuple)
        assert len(result) >= 2
    
    def test_min_score_to_buy_property(self, scoring_engine):
        """Тестирует свойство min_score_to_buy"""
        # Проверяем что свойство существует
        assert hasattr(scoring_engine, 'min_score_to_buy')
        
        # Проверяем что можно устанавливать значение
        original_value = getattr(scoring_engine, 'min_score_to_buy', 0.5)
        scoring_engine.min_score_to_buy = 0.7
        
        # Проверяем что значение изменилось
        assert getattr(scoring_engine, 'min_score_to_buy', 0.5) == 0.7
        
        # Восстанавливаем исходное значение
        scoring_engine.min_score_to_buy = original_value
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    def test_different_ai_scores(self, mock_calc_indicators, scoring_engine, sample_market_df, mock_technical_indicators):
        """Тестирует поведение с разными AI scores"""
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        ai_scores = [0.0, 0.25, 0.5, 0.75, 1.0]
        results = []
        
        for ai_score in ai_scores:
            result = scoring_engine.evaluate(sample_market_df, ai_score=ai_score)
            results.append(result)
        
        # Все результаты должны быть валидными
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) >= 2
            buy_score, ai_score_result = result[0], result[1]
            assert 0.0 <= buy_score <= 1.0
            assert 0.0 <= ai_score_result <= 1.0
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    def test_bullish_indicators(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """Тестирует реакцию на бычьи индикаторы"""
        # Создаем явно бычьи индикаторы
        bullish_indicators = {
            'rsi': 65.0,  # Умеренно перекупленность
            'macd': 1.0,  # Положительный MACD
            'macd_signal': 0.5,
            'macd_hist': 0.5,  # Растущий histogram
            'ema_20': 50200.0,  # EMA20 > EMA50
            'ema_50': 50000.0,
            'stoch_k': 75.0,  # Высокий но не экстремальный Stochastic
            'adx': 30.0,  # Сильный тренд
            'volume_ratio': 1.5  # Высокий объем
        }
        
        mock_df = sample_market_df.copy()
        for key, value in bullish_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.8)
        buy_score = result[0]
        
        # Бычьи индикаторы должны давать высокий score
        assert buy_score > 0.5
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    def test_bearish_indicators(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """Тестирует реакцию на медвежьи индикаторы"""
        # Создаем явно медвежьи индикаторы
        bearish_indicators = {
            'rsi': 25.0,  # Перепроданность
            'macd': -1.0,  # Отрицательный MACD
            'macd_signal': -0.5,
            'macd_hist': -0.5,  # Падающий histogram
            'ema_20': 49800.0,  # EMA20 < EMA50
            'ema_50': 50000.0,
            'stoch_k': 20.0,  # Низкий Stochastic
            'adx': 35.0,  # Сильный тренд (но медвежий)
            'volume_ratio': 0.8  # Низкий объем
        }
        
        mock_df = sample_market_df.copy()
        for key, value in bearish_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.3)
        buy_score = result[0]
        
        # Медвежьи индикаторы должны давать низкий score
        assert buy_score < 0.5


class TestScoringEngineIntegration:
    """Интеграционные тесты для scoring engine"""
    
    def test_real_market_data_simulation(self, scoring_engine):
        """Тестирует с симуляцией реальных рыночных данных"""
        # Создаем более реалистичные данные
        dates = pd.date_range('2024-01-01', periods=200, freq='15min')
        
        # Симулируем разные рыночные условия
        conditions = ['uptrend', 'downtrend', 'sideways']
        
        for condition in conditions:
            if condition == 'uptrend':
                trend = np.linspace(0, 0.1, 200)
                noise = np.random.normal(0, 0.002, 200)
            elif condition == 'downtrend':
                trend = np.linspace(0, -0.1, 200)
                noise = np.random.normal(0, 0.002, 200)
            else:  # sideways
                trend = np.sin(np.linspace(0, 4*np.pi, 200)) * 0.01
                noise = np.random.normal(0, 0.001, 200)
            
            base_price = 50000
            prices = base_price * (1 + trend + noise)
            
            df = pd.DataFrame({
                'open': prices,
                'high': prices * 1.001,
                'low': prices * 0.999,
                'close': prices,
                'volume': np.random.uniform(100, 1000, 200)
            }, index=dates)
            
            # Тестируем что evaluate работает без ошибок
            try:
                result = scoring_engine.evaluate(df, ai_score=0.6)
                assert isinstance(result, tuple)
                assert len(result) >= 2
                
                buy_score = result[0]
                assert 0.0 <= buy_score <= 1.0
                
            except Exception as e:
                pytest.fail(f"Scoring failed for {condition} market: {e}")
    
    def test_performance_with_large_dataset(self, scoring_engine):
        """Тестирует производительность с большим датасетом"""
        # Создаем большой датасет
        dates = pd.date_range('2024-01-01', periods=1000, freq='1min')
        prices = 50000 + np.cumsum(np.random.normal(0, 10, 1000))
        
        large_df = pd.DataFrame({
            'open': prices,
            'high': prices + np.random.uniform(0, 20, 1000),
            'low': prices - np.random.uniform(0, 20, 1000),
            'close': prices,
            'volume': np.random.uniform(100, 1000, 1000)
        }, index=dates)
        
        import time
        start_time = time.time()
        
        result = scoring_engine.evaluate(large_df, ai_score=0.5)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Проверяем что выполнилось за разумное время (< 5 секунд)
        assert execution_time < 5.0, f"Execution took too long: {execution_time:.2f}s"
        
        # Проверяем корректность результата
        assert isinstance(result, tuple)
        assert len(result) >= 2
    
    @patch('analysis.technical_indicators.calculate_all_indicators')
    def test_missing_indicators(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """Тестирует поведение при отсутствии некоторых индикаторов"""
        # Создаем DataFrame с только частью индикаторов
        incomplete_df = sample_market_df.copy()
        incomplete_df['rsi'] = 50.0
        incomplete_df['macd'] = 0.0
        # Остальные индикаторы отсутствуют
        
        mock_calc_indicators.return_value = incomplete_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.6)
        
        # Должен обработать отсутствующие индикаторы без ошибок
        assert isinstance(result, tuple)
        assert len(result) >= 2
        
        buy_score = result[0]
        assert 0.0 <= buy_score <= 1.0


class TestScoringEngineEdgeCases:
    """Тесты граничных случаев"""
    
    def test_extreme_indicator_values(self, scoring_engine, sample_market_df):
        """Тестирует экстремальные значения индикаторов"""
        with patch('analysis.technical_indicators.calculate_all_indicators') as mock_calc:
            extreme_df = sample_market_df.copy()
            extreme_df['rsi'] = 150.0  # Выше нормального диапазона
            extreme_df['macd'] = -1000.0  # Экстремально низкое значение
            extreme_df['adx'] = 200.0  # Выше нормального диапазона
            
            mock_calc.return_value = extreme_df
            
            result = scoring_engine.evaluate(sample_market_df, ai_score=0.5)
            
            # Должен обработать экстремальные значения
            assert isinstance(result, tuple)
            buy_score = result[0]
            assert 0.0 <= buy_score <= 1.0
    
    def test_all_nan_indicators(self, scoring_engine, sample_market_df):
        """Тестирует поведение когда все индикаторы NaN"""
        with patch('analysis.technical_indicators.calculate_all_indicators') as mock_calc:
            nan_df = sample_market_df.copy()
            nan_df['rsi'] = np.nan
            nan_df['macd'] = np.nan
            nan_df['ema_20'] = np.nan
            nan_df['ema_50'] = np.nan
            
            mock_calc.return_value = nan_df
            
            result = scoring_engine.evaluate(sample_market_df, ai_score=0.5)
            
            # Должен обработать NaN значения
            assert isinstance(result, tuple)
            buy_score = result[0]
            assert 0.0 <= buy_score <= 1.0
            assert not np.isnan(buy_score)
    
    def test_single_candle_data(self, scoring_engine):
        """Тестирует данные с одной свечой"""
        single_candle = pd.DataFrame({
            'open': [50000],
            'high': [50100],
            'low': [49900],
            'close': [50000],
            'volume': [1000]
        })
        
        result = scoring_engine.evaluate(single_candle, ai_score=0.5)
        
        assert isinstance(result, tuple)
        assert len(result) >= 2
        
        buy_score = result[0]
        assert 0.0 <= buy_score <= 1.0