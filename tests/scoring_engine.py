import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from analysis.scoring_engine import ScoringEngine


@pytest.fixture
def sample_market_df():
    """РЎРѕР·РґР°РµС‚ РѕР±СЂР°Р·РµС† СЂС‹РЅРѕС‡РЅС‹С… РґР°РЅРЅС‹С… РґР»СЏ С‚РµСЃС‚РёСЂРѕРІР°РЅРёСЏ"""
    dates = pd.date_range('2024-01-01', periods=100, freq='15min')
    
    # РЎРѕР·РґР°РµРј СЂРµР°Р»РёСЃС‚РёС‡РЅС‹Рµ OHLCV РґР°РЅРЅС‹Рµ
    base_price = 50000
    trend = np.linspace(0, 0.05, 100)  # 5% СЂРѕСЃС‚
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
    """РЎРѕР·РґР°РµС‚ СЌРєР·РµРјРїР»СЏСЂ scoring engine"""
    return ScoringEngine()


@pytest.fixture
def mock_technical_indicators():
    """РњРѕРєР°РµС‚ С‚РµС…РЅРёС‡РµСЃРєРёРµ РёРЅРґРёРєР°С‚РѕСЂС‹"""
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
        """РўРµСЃС‚РёСЂСѓРµС‚ РёРЅРёС†РёР°Р»РёР·Р°С†РёСЋ scoring engine"""
        assert hasattr(scoring_engine, 'min_score_to_buy')
        assert hasattr(scoring_engine, 'evaluate')
        assert hasattr(scoring_engine, 'position_fraction')
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    def test_evaluate_basic_functionality(self, mock_calc_indicators, scoring_engine, sample_market_df, mock_technical_indicators):
        """РўРµСЃС‚РёСЂСѓРµС‚ Р±Р°Р·РѕРІСѓСЋ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅРѕСЃС‚СЊ evaluate"""
        # РњРѕРєР°РµРј СЂРµР·СѓР»СЊС‚Р°С‚ calculate_all_indicators
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        # Р’С‹Р·С‹РІР°РµРј evaluate
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.7)
        
        # РџСЂРѕРІРµСЂСЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚
        assert isinstance(result, tuple)
        assert len(result) >= 2
        
        buy_score, ai_score_result = result[0], result[1]
        assert isinstance(buy_score, (int, float))
        assert isinstance(ai_score_result, (int, float))
        assert 0.0 <= buy_score <= 1.0
        assert 0.0 <= ai_score_result <= 1.0
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    def test_evaluate_with_details(self, mock_calc_indicators, scoring_engine, sample_market_df, mock_technical_indicators):
        """РўРµСЃС‚РёСЂСѓРµС‚ evaluate СЃ РІРѕР·РІСЂР°С‰РµРЅРёРµРј РґРµС‚Р°Р»РµР№"""
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.7)
        
        if len(result) >= 3:
            buy_score, ai_score_result, details = result
            assert isinstance(details, dict)
        else:
            # Р•СЃР»Рё РґРµС‚Р°Р»Рё РЅРµ РІРѕР·РІСЂР°С‰Р°СЋС‚СЃСЏ, СЌС‚Рѕ С‚РѕР¶Рµ РІР°Р»РёРґРЅРѕ
            assert len(result) == 2
    
    def test_evaluate_empty_dataframe(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРІРµРґРµРЅРёРµ СЃ РїСѓСЃС‚С‹Рј DataFrame"""
        empty_df = pd.DataFrame()
        
        result = scoring_engine.evaluate(empty_df, ai_score=0.5)
        
        # Р”РѕР»Р¶РµРЅ РІРµСЂРЅСѓС‚СЊ РґРµС„РѕР»С‚РЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ Р±РµР· РѕС€РёР±РѕРє
        assert isinstance(result, tuple)
        buy_score = result[0]
        assert isinstance(buy_score, (int, float))
        assert 0.0 <= buy_score <= 1.0
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    def test_evaluate_exception_handling(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±СЂР°Р±РѕС‚РєСѓ РёСЃРєР»СЋС‡РµРЅРёР№ РІ evaluate"""
        # РњРѕРєР°РµРј РёСЃРєР»СЋС‡РµРЅРёРµ
        mock_calc_indicators.side_effect = Exception("Calculation failed")
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.5)
        
        # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ РёСЃРєР»СЋС‡РµРЅРёРµ Рё РІРµСЂРЅСѓС‚СЊ СЂРµР·СѓР»СЊС‚Р°С‚
        assert isinstance(result, tuple)
        buy_score = result[0]
        assert isinstance(buy_score, (int, float))
    
    def test_position_fraction_basic(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ Р±Р°Р·РѕРІСѓСЋ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅРѕСЃС‚СЊ position_fraction"""
        # РўРµСЃС‚РёСЂСѓРµРј СЂР°Р·РЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ AI score
        test_scores = [0.0, 0.3, 0.5, 0.7, 0.9, 1.0]
        
        for score in test_scores:
            fraction = scoring_engine.position_fraction(score)
            
            assert isinstance(fraction, (int, float))
            assert 0.0 <= fraction <= 1.0
            
            # Р§РµРј РІС‹С€Рµ AI score, С‚РµРј Р±РѕР»СЊС€Рµ РґРѕР»Р¶РЅР° Р±С‹С‚СЊ С„СЂР°РєС†РёСЏ
            if score >= 0.5:
                assert fraction > 0.0
    
    def test_position_fraction_progression(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ С‡С‚Рѕ position_fraction РјРѕРЅРѕС‚РѕРЅРЅРѕ РІРѕР·СЂР°СЃС‚Р°РµС‚"""
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        fractions = [scoring_engine.position_fraction(score) for score in scores]
        
        # РџСЂРѕРІРµСЂСЏРµРј РјРѕРЅРѕС‚РѕРЅРЅРѕСЃС‚СЊ (РЅРµ СЃС‚СЂРѕРіСѓСЋ, РґРѕРїСѓСЃРєР°РµРј СЂР°РІРµРЅСЃС‚РІРѕ)
        for i in range(1, len(fractions)):
            assert fractions[i] >= fractions[i-1], f"Fraction decreased: {fractions[i-1]} -> {fractions[i]}"
    
    def test_position_fraction_edge_cases(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ РіСЂР°РЅРёС‡РЅС‹Рµ СЃР»СѓС‡Р°Рё РґР»СЏ position_fraction"""
        # РћС‚СЂРёС†Р°С‚РµР»СЊРЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ
        assert scoring_engine.position_fraction(-0.5) >= 0.0
        
        # Р—РЅР°С‡РµРЅРёСЏ Р±РѕР»СЊС€Рµ 1
        assert scoring_engine.position_fraction(1.5) <= 1.0
        
        # NaN
        result = scoring_engine.position_fraction(float('nan'))
        assert isinstance(result, (int, float))
        assert not np.isnan(result)
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    @patch('analysis.market_analyzer.MultiTimeframeAnalyzer')
    def test_evaluate_with_market_analyzer(self, mock_analyzer_class, mock_calc_indicators, 
                                         scoring_engine, sample_market_df, mock_technical_indicators):
        """РўРµСЃС‚РёСЂСѓРµС‚ РёРЅС‚РµРіСЂР°С†РёСЋ СЃ market analyzer"""
        # РњРѕРєР°РµРј С‚РµС…РЅРёС‡РµСЃРєРёРµ РёРЅРґРёРєР°С‚РѕСЂС‹
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        # РњРѕРєР°РµРј market analyzer
        mock_analyzer = Mock()
        mock_analyzer.analyze_market_condition.return_value = ("bull", 0.8)
        mock_analyzer_class.return_value = mock_analyzer
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.7)
        
        assert isinstance(result, tuple)
        assert len(result) >= 2
    
    def test_min_score_to_buy_property(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЃРІРѕР№СЃС‚РІРѕ min_score_to_buy"""
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ СЃРІРѕР№СЃС‚РІРѕ СЃСѓС‰РµСЃС‚РІСѓРµС‚
        assert hasattr(scoring_engine, 'min_score_to_buy')
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РјРѕР¶РЅРѕ СѓСЃС‚Р°РЅР°РІР»РёРІР°С‚СЊ Р·РЅР°С‡РµРЅРёРµ
        original_value = getattr(scoring_engine, 'min_score_to_buy', 0.5)
        scoring_engine.min_score_to_buy = 0.7
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ Р·РЅР°С‡РµРЅРёРµ РёР·РјРµРЅРёР»РѕСЃСЊ
        assert getattr(scoring_engine, 'min_score_to_buy', 0.5) == 0.7
        
        # Р’РѕСЃСЃС‚Р°РЅР°РІР»РёРІР°РµРј РёСЃС…РѕРґРЅРѕРµ Р·РЅР°С‡РµРЅРёРµ
        scoring_engine.min_score_to_buy = original_value
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    def test_different_ai_scores(self, mock_calc_indicators, scoring_engine, sample_market_df, mock_technical_indicators):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРІРµРґРµРЅРёРµ СЃ СЂР°Р·РЅС‹РјРё AI scores"""
        mock_df = sample_market_df.copy()
        for key, value in mock_technical_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        ai_scores = [0.0, 0.25, 0.5, 0.75, 1.0]
        results = []
        
        for ai_score in ai_scores:
            result = scoring_engine.evaluate(sample_market_df, ai_score=ai_score)
            results.append(result)
        
        # Р’СЃРµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ РІР°Р»РёРґРЅС‹РјРё
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) >= 2
            buy_score, ai_score_result = result[0], result[1]
            assert 0.0 <= buy_score <= 1.0
            assert 0.0 <= ai_score_result <= 1.0
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    def test_bullish_indicators(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂРµР°РєС†РёСЋ РЅР° Р±С‹С‡СЊРё РёРЅРґРёРєР°С‚РѕСЂС‹"""
        # РЎРѕР·РґР°РµРј СЏРІРЅРѕ Р±С‹С‡СЊРё РёРЅРґРёРєР°С‚РѕСЂС‹
        bullish_indicators = {
            'rsi': 65.0,  # РЈРјРµСЂРµРЅРЅРѕ РїРµСЂРµРєСѓРїР»РµРЅРЅРѕСЃС‚СЊ
            'macd': 1.0,  # РџРѕР»РѕР¶РёС‚РµР»СЊРЅС‹Р№ MACD
            'macd_signal': 0.5,
            'macd_hist': 0.5,  # Р Р°СЃС‚СѓС‰РёР№ histogram
            'ema_20': 50200.0,  # EMA20 > EMA50
            'ema_50': 50000.0,
            'stoch_k': 75.0,  # Р’С‹СЃРѕРєРёР№ РЅРѕ РЅРµ СЌРєСЃС‚СЂРµРјР°Р»СЊРЅС‹Р№ Stochastic
            'adx': 30.0,  # РЎРёР»СЊРЅС‹Р№ С‚СЂРµРЅРґ
            'volume_ratio': 1.5  # Р’С‹СЃРѕРєРёР№ РѕР±СЉРµРј
        }
        
        mock_df = sample_market_df.copy()
        for key, value in bullish_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.8)
        buy_score = result[0]
        
        # Р‘С‹С‡СЊРё РёРЅРґРёРєР°С‚РѕСЂС‹ РґРѕР»Р¶РЅС‹ РґР°РІР°С‚СЊ РІС‹СЃРѕРєРёР№ score
        assert buy_score > 0.5
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    def test_bearish_indicators(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂРµР°РєС†РёСЋ РЅР° РјРµРґРІРµР¶СЊРё РёРЅРґРёРєР°С‚РѕСЂС‹"""
        # РЎРѕР·РґР°РµРј СЏРІРЅРѕ РјРµРґРІРµР¶СЊРё РёРЅРґРёРєР°С‚РѕСЂС‹
        bearish_indicators = {
            'rsi': 25.0,  # РџРµСЂРµРїСЂРѕРґР°РЅРЅРѕСЃС‚СЊ
            'macd': -1.0,  # РћС‚СЂРёС†Р°С‚РµР»СЊРЅС‹Р№ MACD
            'macd_signal': -0.5,
            'macd_hist': -0.5,  # РџР°РґР°СЋС‰РёР№ histogram
            'ema_20': 49800.0,  # EMA20 < EMA50
            'ema_50': 50000.0,
            'stoch_k': 20.0,  # РќРёР·РєРёР№ Stochastic
            'adx': 35.0,  # РЎРёР»СЊРЅС‹Р№ С‚СЂРµРЅРґ (РЅРѕ РјРµРґРІРµР¶РёР№)
            'volume_ratio': 0.8  # РќРёР·РєРёР№ РѕР±СЉРµРј
        }
        
        mock_df = sample_market_df.copy()
        for key, value in bearish_indicators.items():
            mock_df[key] = value
        mock_calc_indicators.return_value = mock_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.3)
        buy_score = result[0]
        
        # РњРµРґРІРµР¶СЊРё РёРЅРґРёРєР°С‚РѕСЂС‹ РґРѕР»Р¶РЅС‹ РґР°РІР°С‚СЊ РЅРёР·РєРёР№ score
        assert buy_score < 0.5


class TestScoringEngineIntegration:
    """РРЅС‚РµРіСЂР°С†РёРѕРЅРЅС‹Рµ С‚РµСЃС‚С‹ РґР»СЏ scoring engine"""
    
    def test_real_market_data_simulation(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЃ СЃРёРјСѓР»СЏС†РёРµР№ СЂРµР°Р»СЊРЅС‹С… СЂС‹РЅРѕС‡РЅС‹С… РґР°РЅРЅС‹С…"""
        # РЎРѕР·РґР°РµРј Р±РѕР»РµРµ СЂРµР°Р»РёСЃС‚РёС‡РЅС‹Рµ РґР°РЅРЅС‹Рµ
        dates = pd.date_range('2024-01-01', periods=200, freq='15min')
        
        # РЎРёРјСѓР»РёСЂСѓРµРј СЂР°Р·РЅС‹Рµ СЂС‹РЅРѕС‡РЅС‹Рµ СѓСЃР»РѕРІРёСЏ
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
            
            # РўРµСЃС‚РёСЂСѓРµРј С‡С‚Рѕ evaluate СЂР°Р±РѕС‚Р°РµС‚ Р±РµР· РѕС€РёР±РѕРє
            try:
                result = scoring_engine.evaluate(df, ai_score=0.6)
                assert isinstance(result, tuple)
                assert len(result) >= 2
                
                buy_score = result[0]
                assert 0.0 <= buy_score <= 1.0
                
            except Exception as e:
                pytest.fail(f"Scoring failed for {condition} market: {e}")
    
    def test_performance_with_large_dataset(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚СЊ СЃ Р±РѕР»СЊС€РёРј РґР°С‚Р°СЃРµС‚РѕРј"""
        # РЎРѕР·РґР°РµРј Р±РѕР»СЊС€РѕР№ РґР°С‚Р°СЃРµС‚
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
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІС‹РїРѕР»РЅРёР»РѕСЃСЊ Р·Р° СЂР°Р·СѓРјРЅРѕРµ РІСЂРµРјСЏ (< 5 СЃРµРєСѓРЅРґ)
        assert execution_time < 5.0, f"Execution took too long: {execution_time:.2f}s"
        
        # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ СЂРµР·СѓР»СЊС‚Р°С‚Р°
        assert isinstance(result, tuple)
        assert len(result) >= 2
    
    @patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators')
    def test_missing_indicators(self, mock_calc_indicators, scoring_engine, sample_market_df):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРІРµРґРµРЅРёРµ РїСЂРё РѕС‚СЃСѓС‚СЃС‚РІРёРё РЅРµРєРѕС‚РѕСЂС‹С… РёРЅРґРёРєР°С‚РѕСЂРѕРІ"""
        # РЎРѕР·РґР°РµРј DataFrame СЃ С‚РѕР»СЊРєРѕ С‡Р°СЃС‚СЊСЋ РёРЅРґРёРєР°С‚РѕСЂРѕРІ
        incomplete_df = sample_market_df.copy()
        incomplete_df['rsi'] = 50.0
        incomplete_df['macd'] = 0.0
        # РћСЃС‚Р°Р»СЊРЅС‹Рµ РёРЅРґРёРєР°С‚РѕСЂС‹ РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‚
        
        mock_calc_indicators.return_value = incomplete_df
        
        result = scoring_engine.evaluate(sample_market_df, ai_score=0.6)
        
        # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РёРµ РёРЅРґРёРєР°С‚РѕСЂС‹ Р±РµР· РѕС€РёР±РѕРє
        assert isinstance(result, tuple)
        assert len(result) >= 2
        
        buy_score = result[0]
        assert 0.0 <= buy_score <= 1.0


class TestScoringEngineEdgeCases:
    """РўРµСЃС‚С‹ РіСЂР°РЅРёС‡РЅС‹С… СЃР»СѓС‡Р°РµРІ"""
    
    def test_extreme_indicator_values(self, scoring_engine, sample_market_df):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЌРєСЃС‚СЂРµРјР°Р»СЊРЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ РёРЅРґРёРєР°С‚РѕСЂРѕРІ"""
        with patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators') as mock_calc:
            extreme_df = sample_market_df.copy()
            extreme_df['rsi'] = 150.0  # Р’С‹С€Рµ РЅРѕСЂРјР°Р»СЊРЅРѕРіРѕ РґРёР°РїР°Р·РѕРЅР°
            extreme_df['macd'] = -1000.0  # Р­РєСЃС‚СЂРµРјР°Р»СЊРЅРѕ РЅРёР·РєРѕРµ Р·РЅР°С‡РµРЅРёРµ
            extreme_df['adx'] = 200.0  # Р’С‹С€Рµ РЅРѕСЂРјР°Р»СЊРЅРѕРіРѕ РґРёР°РїР°Р·РѕРЅР°
            
            mock_calc.return_value = extreme_df
            
            result = scoring_engine.evaluate(sample_market_df, ai_score=0.5)
            
            # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ СЌРєСЃС‚СЂРµРјР°Р»СЊРЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ
            assert isinstance(result, tuple)
            buy_score = result[0]
            assert 0.0 <= buy_score <= 1.0
    
    def test_all_nan_indicators(self, scoring_engine, sample_market_df):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРІРµРґРµРЅРёРµ РєРѕРіРґР° РІСЃРµ РёРЅРґРёРєР°С‚РѕСЂС‹ NaN"""
        with patch('crypto_ai_bot.core.indicators.unified.calculate_all_indicators') as mock_calc:
            nan_df = sample_market_df.copy()
            nan_df['rsi'] = np.nan
            nan_df['macd'] = np.nan
            nan_df['ema_20'] = np.nan
            nan_df['ema_50'] = np.nan
            
            mock_calc.return_value = nan_df
            
            result = scoring_engine.evaluate(sample_market_df, ai_score=0.5)
            
            # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ NaN Р·РЅР°С‡РµРЅРёСЏ
            assert isinstance(result, tuple)
            buy_score = result[0]
            assert 0.0 <= buy_score <= 1.0
            assert not np.isnan(buy_score)
    
    def test_single_candle_data(self, scoring_engine):
        """РўРµСЃС‚РёСЂСѓРµС‚ РґР°РЅРЅС‹Рµ СЃ РѕРґРЅРѕР№ СЃРІРµС‡РѕР№"""
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



