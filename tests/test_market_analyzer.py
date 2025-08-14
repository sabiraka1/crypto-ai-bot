import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch
from analysis.market_analyzer import MultiTimeframeAnalyzer
from config.settings import MarketCondition


@pytest.fixture
def sample_market_data():
    """РЎРѕР·РґР°РµС‚ РѕР±СЂР°Р·С†С‹ СЂС‹РЅРѕС‡РЅС‹С… РґР°РЅРЅС‹С… РґР»СЏ С‚РµСЃС‚РёСЂРѕРІР°РЅРёСЏ"""
    dates_1d = pd.date_range('2024-01-01', periods=50, freq='D')
    dates_4h = pd.date_range('2024-01-01', periods=200, freq='4h')
    
    # РЎРѕР·РґР°РµРј С‚СЂРµРЅРґРѕРІС‹Рµ РґР°РЅРЅС‹Рµ (РІРѕСЃС…РѕРґСЏС‰РёР№ С‚СЂРµРЅРґ)
    base_price = 50000
    trend_1d = np.linspace(0, 0.2, 50)  # 20% СЂРѕСЃС‚ Р·Р° РїРµСЂРёРѕРґ
    trend_4h = np.linspace(0, 0.2, 200)
    
    # Р”РѕР±Р°РІР»СЏРµРј С€СѓРј
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
    """РЎРѕР·РґР°РµС‚ РґР°РЅРЅС‹Рµ Р±РѕРєРѕРІРѕРіРѕ РґРІРёР¶РµРЅРёСЏ"""
    dates = pd.date_range('2024-01-01', periods=50, freq='D')
    base_price = 50000
    noise = np.random.normal(0, 0.005, 50)  # РњР°Р»С‹Р№ С€СѓРј
    
    df = pd.DataFrame({
        'open': base_price * (1 + noise),
        'high': base_price * (1 + noise + 0.003),
        'low': base_price * (1 + noise - 0.003),
        'close': base_price * (1 + noise),
        'volume': np.random.uniform(1000, 3000, 50)
    }, index=dates)
    
    return df, df.copy()  # Р’РѕР·РІСЂР°С‰Р°РµРј РѕРґРёРЅР°РєРѕРІС‹Рµ РґР°РЅРЅС‹Рµ РґР»СЏ 1D Рё 4H


@pytest.fixture
def analyzer():
    """РЎРѕР·РґР°РµС‚ СЌРєР·РµРјРїР»СЏСЂ Р°РЅР°Р»РёР·Р°С‚РѕСЂР°"""
    return MultiTimeframeAnalyzer()


class TestMultiTimeframeAnalyzer:
    
    def test_analyzer_initialization(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РёРЅРёС†РёР°Р»РёР·Р°С†РёСЋ Р°РЅР°Р»РёР·Р°С‚РѕСЂР°"""
        assert analyzer._w_daily == 0.6
        assert analyzer._w_h4 == 0.4
        assert analyzer._ema_fast == 20
        assert analyzer._ema_slow == 50
        assert analyzer._momentum_lookback == 20
        assert analyzer._vol_window == 60
        assert analyzer._atr_period == 14
    
    def test_analyze_market_condition_bull(self, analyzer, sample_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ Р°РЅР°Р»РёР· Р±С‹С‡СЊРµРіРѕ СЂС‹РЅРєР°"""
        df_1d, df_4h = sample_market_data
        
        condition, confidence = analyzer.analyze_market_condition(df_1d, df_4h)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РѕРїСЂРµРґРµР»РёР»СЃСЏ Р±С‹С‡РёР№ С‚СЂРµРЅРґ
        assert condition in [MarketCondition.WEAK_BULL, MarketCondition.STRONG_BULL]
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.1  # Р”РѕР»Р¶РЅР° Р±С‹С‚СЊ РЅРµРєРѕС‚РѕСЂР°СЏ СѓРІРµСЂРµРЅРЅРѕСЃС‚СЊ
    
    def test_analyze_market_condition_sideways(self, analyzer, sideways_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ Р°РЅР°Р»РёР· Р±РѕРєРѕРІРѕРіРѕ СЂС‹РЅРєР°"""
        df_1d, df_4h = sideways_market_data
        
        condition, confidence = analyzer.analyze_market_condition(df_1d, df_4h)
        
        # Р‘РѕРєРѕРІРѕР№ СЂС‹РЅРѕРє РґРѕР»Р¶РµРЅ РѕРїСЂРµРґРµР»СЏС‚СЊСЃСЏ РєР°Рє SIDEWAYS
        assert condition == MarketCondition.SIDEWAYS
        assert 0.0 <= confidence <= 1.0
    
    def test_analyze_empty_data(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРІРµРґРµРЅРёРµ СЃ РїСѓСЃС‚С‹РјРё РґР°РЅРЅС‹РјРё"""
        empty_df = pd.DataFrame()
        
        condition, confidence = analyzer.analyze_market_condition(empty_df, empty_df)
        
        assert condition == MarketCondition.SIDEWAYS
        assert confidence == 0.10
    
    def test_analyze_invalid_data(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРІРµРґРµРЅРёРµ СЃ РЅРµРєРѕСЂСЂРµРєС‚РЅС‹РјРё РґР°РЅРЅС‹РјРё"""
        # DataFrame Р±РµР· РЅСѓР¶РЅС‹С… РєРѕР»РѕРЅРѕРє
        bad_df = pd.DataFrame({'wrong_col': [1, 2, 3]})
        
        condition, confidence = analyzer.analyze_market_condition(bad_df, bad_df)
        
        assert condition == MarketCondition.SIDEWAYS
        assert confidence == 0.10
    
    def test_trend_calculation(self, analyzer, sample_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂР°СЃС‡РµС‚ С‚СЂРµРЅРґР°"""
        df_1d, _ = sample_market_data
        
        trend = analyzer._trend(df_1d)
        
        assert isinstance(trend, float)
        assert -1.0 <= trend <= 1.0
        # Р”Р»СЏ РІРѕСЃС…РѕРґСЏС‰РёС… РґР°РЅРЅС‹С… С‚СЂРµРЅРґ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РїРѕР»РѕР¶РёС‚РµР»СЊРЅС‹Рј
        assert trend > 0
    
    def test_trend_empty_data(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂР°СЃС‡РµС‚ С‚СЂРµРЅРґР° СЃ РїСѓСЃС‚С‹РјРё РґР°РЅРЅС‹РјРё"""
        empty_df = pd.DataFrame()
        
        trend = analyzer._trend(empty_df)
        
        assert trend == 0.0
    
    def test_strength_calculation(self, analyzer, sample_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂР°СЃС‡РµС‚ СЃРёР»С‹ С‚СЂРµРЅРґР°"""
        df_1d, _ = sample_market_data
        
        strength = analyzer._strength(df_1d)
        
        assert isinstance(strength, float)
        assert 0.0 <= strength <= 1.0
    
    @patch('crypto_ai_bot.core.indicators.unified._atr_series_for_ml')
    def test_strength_with_unified_atr(self, mock_atr, analyzer, sample_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂР°СЃС‡РµС‚ СЃРёР»С‹ СЃ unified ATR"""
        df_1d, _ = sample_market_data
        
        # РњРѕРєР°РµРј unified ATR
        mock_atr_series = pd.Series([100.0] * len(df_1d), index=df_1d.index)
        mock_atr.return_value = mock_atr_series
        
        strength = analyzer._strength(df_1d)
        
        assert isinstance(strength, float)
        assert 0.0 <= strength <= 1.0
        mock_atr.assert_called_once()
    
    @patch('crypto_ai_bot.core.indicators.unified._atr_series_for_ml')
    def test_strength_atr_fallback(self, mock_atr, analyzer, sample_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ fallback РїСЂРё РѕС€РёР±РєРµ unified ATR"""
        df_1d, _ = sample_market_data
        
        # РњРѕРєР°РµРј РёСЃРєР»СЋС‡РµРЅРёРµ РІ unified ATR
        mock_atr.side_effect = Exception("ATR calculation failed")
        
        strength = analyzer._strength(df_1d)
        
        # Р”РѕР»Р¶РµРЅ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ fallback
        assert isinstance(strength, float)
        assert 0.0 <= strength <= 1.0
    
    def test_classify_conditions(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєР»Р°СЃСЃРёС„РёРєР°С†РёСЋ СЂС‹РЅРѕС‡РЅС‹С… СѓСЃР»РѕРІРёР№"""
        # РЎРёР»СЊРЅС‹Р№ Р±С‹Рє
        condition = analyzer._classify(0.15, 0.8)
        assert condition == MarketCondition.STRONG_BULL
        
        # РЎР»Р°Р±С‹Р№ Р±С‹Рє
        condition = analyzer._classify(0.07, 0.6)
        assert condition == MarketCondition.WEAK_BULL
        
        # РЎРёР»СЊРЅС‹Р№ РјРµРґРІРµРґСЊ
        condition = analyzer._classify(-0.15, 0.8)
        assert condition == MarketCondition.STRONG_BEAR
        
        # РЎР»Р°Р±С‹Р№ РјРµРґРІРµРґСЊ
        condition = analyzer._classify(-0.07, 0.6)
        assert condition == MarketCondition.WEAK_BEAR
        
        # Р‘РѕРєРѕРІРёРє
        condition = analyzer._classify(0.02, 0.4)
        assert condition == MarketCondition.SIDEWAYS
    
    def test_get_diagnostics(self, analyzer, sample_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ РґРёР°РіРЅРѕСЃС‚РёС‡РµСЃРєРёРµ РјРµС‚РѕРґС‹"""
        df_1d, df_4h = sample_market_data
        
        diagnostics = analyzer.get_diagnostics(df_1d, df_4h)
        
        # РџСЂРѕРІРµСЂСЏРµРј СЃС‚СЂСѓРєС‚СѓСЂСѓ РґРёР°РіРЅРѕСЃС‚РёРєРё
        assert 'timeframes' in diagnostics
        assert 'combined' in diagnostics
        assert 'weights' in diagnostics
        assert 'parameters' in diagnostics
        
        # РџСЂРѕРІРµСЂСЏРµРј РґР°РЅРЅС‹Рµ РїРѕ С‚Р°Р№РјС„СЂРµР№РјР°Рј
        assert '1d' in diagnostics['timeframes']
        assert '4h' in diagnostics['timeframes']
        
        # РџСЂРѕРІРµСЂСЏРµРј РєРѕРјР±РёРЅРёСЂРѕРІР°РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ
        combined = diagnostics['combined']
        assert 'trend' in combined
        assert 'strength' in combined
        assert 'condition' in combined
        assert 'confidence' in combined
        
        # РџСЂРѕРІРµСЂСЏРµРј РІРµСЃР°
        weights = diagnostics['weights']
        assert weights['daily'] == 0.6
        assert weights['4h'] == 0.4
    
    def test_get_diagnostics_error_handling(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±СЂР°Р±РѕС‚РєСѓ РѕС€РёР±РѕРє РІ РґРёР°РіРЅРѕСЃС‚РёРєРµ"""
        # РџРµСЂРµРґР°РµРј None РґР°РЅРЅС‹Рµ
        diagnostics = analyzer.get_diagnostics(None, None)
        
        assert 'error' in diagnostics
    
    def test_validate_data_quality_good_data(self, analyzer, sample_market_data):
        """РўРµСЃС‚РёСЂСѓРµС‚ РІР°Р»РёРґР°С†РёСЋ РєР°С‡РµСЃС‚РІРµРЅРЅС‹С… РґР°РЅРЅС‹С…"""
        df_1d, df_4h = sample_market_data
        
        validation = analyzer.validate_data_quality(df_1d, df_4h)
        
        assert validation['valid'] is True
        assert len(validation['issues']) == 0
        assert 'data_quality' in validation
        assert validation['data_quality']['1d_rows'] == len(df_1d)
        assert validation['data_quality']['4h_rows'] == len(df_4h)
    
    def test_validate_data_quality_empty_data(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РІР°Р»РёРґР°С†РёСЋ РїСѓСЃС‚С‹С… РґР°РЅРЅС‹С…"""
        empty_df = pd.DataFrame()
        
        validation = analyzer.validate_data_quality(empty_df, empty_df)
        
        assert validation['valid'] is False
        assert len(validation['issues']) > 0
        assert any('empty' in issue.lower() for issue in validation['issues'])
    
    def test_validate_data_quality_missing_columns(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РІР°Р»РёРґР°С†РёСЋ РґР°РЅРЅС‹С… СЃ РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РёРјРё РєРѕР»РѕРЅРєР°РјРё"""
        bad_df = pd.DataFrame({'only_close': [1, 2, 3, 4, 5]})
        
        validation = analyzer.validate_data_quality(bad_df, bad_df)
        
        assert validation['valid'] is False
        assert any('missing columns' in issue.lower() for issue in validation['issues'])
    
    def test_validate_data_quality_insufficient_rows(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РІР°Р»РёРґР°С†РёСЋ РґР°РЅРЅС‹С… СЃ РЅРµРґРѕСЃС‚Р°С‚РѕС‡РЅС‹Рј РєРѕР»РёС‡РµСЃС‚РІРѕРј СЃС‚СЂРѕРє"""
        # РЎРѕР·РґР°РµРј РґР°РЅРЅС‹Рµ СЃ РјР°Р»С‹Рј РєРѕР»РёС‡РµСЃС‚РІРѕРј СЃС‚СЂРѕРє
        small_df = pd.DataFrame({
            'open': [1, 2],
            'high': [1.1, 2.1],
            'low': [0.9, 1.9],
            'close': [1.05, 2.05],
            'volume': [100, 200]
        })
        
        validation = analyzer.validate_data_quality(small_df, small_df)
        
        # РњРѕР¶РµС‚ Р±С‹С‚СЊ РІР°Р»РёРґРЅС‹Рј, РЅРѕ РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ РїСЂРµРґСѓРїСЂРµР¶РґРµРЅРёСЏ
        assert len(validation['warnings']) > 0
        assert any('rows' in warning.lower() for warning in validation['warnings'])
    
    def test_get_configuration(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕР»СѓС‡РµРЅРёРµ РєРѕРЅС„РёРіСѓСЂР°С†РёРё"""
        config = analyzer.get_configuration()
        
        assert 'timeframe_weights' in config
        assert 'ema_parameters' in config
        assert 'analysis_parameters' in config
        assert 'classification_thresholds' in config
        
        # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ Р·РЅР°С‡РµРЅРёР№
        assert config['timeframe_weights']['daily'] == 0.6
        assert config['ema_parameters']['fast'] == 20
        assert config['analysis_parameters']['atr_period'] == 14
    
    def test_update_configuration(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±РЅРѕРІР»РµРЅРёРµ РєРѕРЅС„РёРіСѓСЂР°С†РёРё"""
        # РћР±РЅРѕРІР»СЏРµРј РЅРµСЃРєРѕР»СЊРєРѕ РїР°СЂР°РјРµС‚СЂРѕРІ
        updated = analyzer.update_configuration(
            w_daily=0.7,
            ema_fast=15,
            atr_period=21
        )
        
        assert 'w_daily' in updated
        assert 'ema_fast' in updated
        assert 'atr_period' in updated
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ Р·РЅР°С‡РµРЅРёСЏ РґРµР№СЃС‚РІРёС‚РµР»СЊРЅРѕ РѕР±РЅРѕРІРёР»РёСЃСЊ
        assert analyzer._w_daily == 0.7
        assert analyzer._ema_fast == 15
        assert analyzer._atr_period == 21
    
    def test_update_configuration_invalid_params(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±РЅРѕРІР»РµРЅРёРµ СЃ РЅРµРІР°Р»РёРґРЅС‹РјРё РїР°СЂР°РјРµС‚СЂР°РјРё"""
        updated = analyzer.update_configuration(
            invalid_param=123,
            another_invalid=456
        )
        
        assert len(updated) == 0  # РќРёС‡РµРіРѕ РЅРµ РґРѕР»Р¶РЅРѕ РѕР±РЅРѕРІРёС‚СЊСЃСЏ
    
    def test_with_nan_data(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂР°Р±РѕС‚Сѓ СЃ РґР°РЅРЅС‹РјРё СЃРѕРґРµСЂР¶Р°С‰РёРјРё NaN"""
        # РЎРѕР·РґР°РµРј РґР°РЅРЅС‹Рµ СЃ NaN
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        df_with_nan = pd.DataFrame({
            'open': [50000] * 30,
            'high': [50100] * 30,
            'low': [49900] * 30,
            'close': [50000] * 30,
            'volume': [1000] * 30
        }, index=dates)
        
        # Р”РѕР±Р°РІР»СЏРµРј NaN РІ РЅРµСЃРєРѕР»СЊРєРѕ РјРµСЃС‚
        df_with_nan.loc[df_with_nan.index[5], 'close'] = np.nan
        df_with_nan.loc[df_with_nan.index[10], 'volume'] = np.nan
        
        condition, confidence = analyzer.analyze_market_condition(df_with_nan, df_with_nan)
        
        # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ NaN Р±РµР· РѕС€РёР±РѕРє
        assert isinstance(condition, MarketCondition)
        assert 0.0 <= confidence <= 1.0
    
    def test_extreme_values(self, analyzer):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЂР°Р±РѕС‚Сѓ СЃ СЌРєСЃС‚СЂРµРјР°Р»СЊРЅС‹РјРё Р·РЅР°С‡РµРЅРёСЏРјРё"""
        # РЎРѕР·РґР°РµРј РґР°РЅРЅС‹Рµ СЃ РѕС‡РµРЅСЊ Р±РѕР»СЊС€РёРјРё РёР·РјРµРЅРµРЅРёСЏРјРё
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        prices = [50000 * (1.1 ** i) for i in range(30)]  # Р­РєСЃРїРѕРЅРµРЅС†РёР°Р»СЊРЅС‹Р№ СЂРѕСЃС‚
        
        df_extreme = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [1000] * 30
        }, index=dates)
        
        condition, confidence = analyzer.analyze_market_condition(df_extreme, df_extreme)
        
        # Р”РѕР»Р¶РµРЅ РѕРїСЂРµРґРµР»РёС‚СЊ СЃРёР»СЊРЅС‹Р№ Р±С‹С‡РёР№ С‚СЂРµРЅРґ
        assert condition in [MarketCondition.WEAK_BULL, MarketCondition.STRONG_BULL]
        assert confidence > 0.3  # Р’С‹СЃРѕРєР°СЏ СѓРІРµСЂРµРЅРЅРѕСЃС‚СЊ РґР»СЏ С‚Р°РєРѕРіРѕ С‚СЂРµРЅРґР°


class TestEdgeCases:
    """РўРµСЃС‚С‹ РіСЂР°РЅРёС‡РЅС‹С… СЃР»СѓС‡Р°РµРІ"""
    
    def test_single_row_data(self):
        """РўРµСЃС‚РёСЂСѓРµС‚ РґР°РЅРЅС‹Рµ СЃ РѕРґРЅРѕР№ СЃС‚СЂРѕРєРѕР№"""
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
        """РўРµСЃС‚РёСЂСѓРµС‚ РґР°РЅРЅС‹Рµ СЃ РЅСѓР»РµРІС‹Рј РѕР±СЉРµРјРѕРј"""
        analyzer = MultiTimeframeAnalyzer()
        
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        zero_volume_df = pd.DataFrame({
            'open': [50000] * 30,
            'high': [50100] * 30,
            'low': [49900] * 30,
            'close': [50000] * 30,
            'volume': [0] * 30  # РќСѓР»РµРІРѕР№ РѕР±СЉРµРј
        }, index=dates)
        
        condition, confidence = analyzer.analyze_market_condition(zero_volume_df, zero_volume_df)
        
        # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ Р±РµР· РѕС€РёР±РѕРє
        assert isinstance(condition, MarketCondition)
        assert 0.0 <= confidence <= 1.0


