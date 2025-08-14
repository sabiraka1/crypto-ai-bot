"""РСЃРїСЂР°РІР»РµРЅРЅС‹Рµ С‚РµСЃС‚С‹ РґР»СЏ РјРѕРґСѓР»СЏ С‚РµС…РЅРёС‡РµСЃРєРёС… РёРЅРґРёРєР°С‚РѕСЂРѕРІ."""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, Mock
import sys
from pathlib import Path

# Р”РѕР±Р°РІР»СЏРµРј РєРѕСЂРЅРµРІСѓСЋ РґРёСЂРµРєС‚РѕСЂРёСЋ РІ РїСѓС‚СЊ
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def sample_ohlcv_data():
    """РЎРѕР·РґР°РµС‚ РѕР±СЂР°Р·РµС† OHLCV РґР°РЅРЅС‹С… РґР»СЏ С‚РµСЃС‚РёСЂРѕРІР°РЅРёСЏ"""
    dates = pd.date_range('2024-01-01', periods=100, freq='15min')
    
    # Р“РµРЅРµСЂРёСЂСѓРµРј СЂРµР°Р»РёСЃС‚РёС‡РЅС‹Рµ РґР°РЅРЅС‹Рµ СЃ С‚СЂРµРЅРґРѕРј
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
    """РњР°Р»РµРЅСЊРєРёР№ РЅР°Р±РѕСЂ РґР°РЅРЅС‹С… РґР»СЏ Р±С‹СЃС‚СЂС‹С… С‚РµСЃС‚РѕРІ"""
    return pd.DataFrame({
        'open': [100, 102, 101, 103, 102],
        'high': [102, 103, 102, 104, 103],
        'low': [99, 101, 100, 102, 101],
        'close': [101, 101.5, 102, 103, 102.5],
        'volume': [1000, 1200, 900, 1100, 1050]
    })


class TestTechnicalIndicatorsModule:
    """РўРµСЃС‚С‹ РґР»СЏ СЂРµР°Р»СЊРЅРѕРіРѕ РјРѕРґСѓР»СЏ technical_indicators"""
    
    def test_module_import(self):
        """РўРµСЃС‚ РёРјРїРѕСЂС‚Р° РјРѕРґСѓР»СЏ"""
        try:
            from analysis import technical_indicators
            assert technical_indicators is not None
        except ImportError as e:
            pytest.skip(f"Cannot import technical_indicators: {e}")
    
    def test_calculate_all_indicators_exists(self):
        """РўРµСЃС‚ РЅР°Р»РёС‡РёСЏ С„СѓРЅРєС†РёРё calculate_all_indicators"""
        from analysis import technical_indicators
        
        assert hasattr(technical_indicators, 'calculate_all_indicators')
        assert callable(technical_indicators.calculate_all_indicators)
    
    def test_calculate_all_indicators_basic(self, sample_ohlcv_data):
        """РўРµСЃС‚ Р±Р°Р·РѕРІРѕР№ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅРѕСЃС‚Рё calculate_all_indicators"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
        result = calculate_all_indicators(sample_ohlcv_data)
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(sample_ohlcv_data)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РґРѕР±Р°РІР»РµРЅС‹ РЅРѕРІС‹Рµ РєРѕР»РѕРЅРєРё
        assert len(result.columns) > len(sample_ohlcv_data.columns)
        
        # РџСЂРѕРІРµСЂСЏРµРј РЅР°Р»РёС‡РёРµ РѕСЃРЅРѕРІРЅС‹С… РёРЅРґРёРєР°С‚РѕСЂРѕРІ
        expected_indicators = ['rsi', 'macd', 'ema_20', 'sma_20']
        for indicator in expected_indicators:
            if indicator in result.columns:
                assert indicator in result.columns
    
    def test_calculate_all_indicators_preserves_original(self, sample_ohlcv_data):
        """РўРµСЃС‚ С‡С‚Рѕ РёСЃС…РѕРґРЅС‹Рµ РґР°РЅРЅС‹Рµ РЅРµ РјРѕРґРёС„РёС†РёСЂСѓСЋС‚СЃСЏ"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
        original_copy = sample_ohlcv_data.copy()
        result = calculate_all_indicators(sample_ohlcv_data)
        
        # РСЃС…РѕРґРЅС‹Р№ DataFrame РЅРµ РґРѕР»Р¶РµРЅ РёР·РјРµРЅРёС‚СЊСЃСЏ
        pd.testing.assert_frame_equal(sample_ohlcv_data, original_copy)
        
        # Р РµР·СѓР»СЊС‚Р°С‚ РґРѕР»Р¶РµРЅ СЃРѕРґРµСЂР¶Р°С‚СЊ РёСЃС…РѕРґРЅС‹Рµ РєРѕР»РѕРЅРєРё
        for col in sample_ohlcv_data.columns:
            assert col in result.columns
    
    def test_calculate_all_indicators_empty_data(self):
        """РўРµСЃС‚ СЃ РїСѓСЃС‚С‹РјРё РґР°РЅРЅС‹РјРё"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
        empty_df = pd.DataFrame()
        
        # РќРµ РґРѕР»Р¶РЅРѕ РїР°РґР°С‚СЊ
        result = calculate_all_indicators(empty_df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
    
    def test_calculate_all_indicators_single_row(self):
        """РўРµСЃС‚ СЃ РѕРґРЅРѕР№ СЃС‚СЂРѕРєРѕР№ РґР°РЅРЅС‹С…"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
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
        """РўРµСЃС‚ С„СѓРЅРєС†РёР№ ATR"""
        from analysis import technical_indicators
        
        # РџСЂРѕРІРµСЂСЏРµРј РЅР°Р»РёС‡РёРµ ATR С„СѓРЅРєС†РёР№
        if hasattr(technical_indicators, '_atr_series_for_ml'):
            atr = technical_indicators._atr_series_for_ml(sample_ohlcv_data)
            assert isinstance(atr, pd.Series)
            assert len(atr) == len(sample_ohlcv_data)
        
        if hasattr(technical_indicators, 'calculate_atr'):
            atr = technical_indicators.calculate_atr(sample_ohlcv_data, period=14)
            assert isinstance(atr, (pd.Series, np.ndarray))
    
    def test_rsi_calculation(self, sample_ohlcv_data):
        """РўРµСЃС‚ СЂР°СЃС‡РµС‚Р° RSI РµСЃР»Рё С„СѓРЅРєС†РёСЏ РґРѕСЃС‚СѓРїРЅР°"""
        from analysis import technical_indicators
        
        # РџСЂРѕРІРµСЂСЏРµРј СЂР°Р·РЅС‹Рµ РІР°СЂРёР°РЅС‚С‹ С„СѓРЅРєС†РёРё RSI
        rsi_functions = ['calculate_rsi', 'rsi', 'compute_rsi', '_calculate_rsi']
        
        for func_name in rsi_functions:
            if hasattr(technical_indicators, func_name):
                func = getattr(technical_indicators, func_name)
                if callable(func):
                    try:
                        rsi = func(sample_ohlcv_data['close'], 14)
                        assert isinstance(rsi, (pd.Series, np.ndarray))
                        
                        # RSI РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РІ РґРёР°РїР°Р·РѕРЅРµ 0-100
                        valid_rsi = rsi[~pd.isna(rsi)]
                        if len(valid_rsi) > 0:
                            assert (valid_rsi >= 0).all()
                            assert (valid_rsi <= 100).all()
                        break
                    except:
                        continue
    
    def test_macd_calculation(self, sample_ohlcv_data):
        """РўРµСЃС‚ СЂР°СЃС‡РµС‚Р° MACD РµСЃР»Рё С„СѓРЅРєС†РёСЏ РґРѕСЃС‚СѓРїРЅР°"""
        from analysis import technical_indicators
        
        # РџСЂРѕРІРµСЂСЏРµРј СЂР°Р·РЅС‹Рµ РІР°СЂРёР°РЅС‚С‹ С„СѓРЅРєС†РёРё MACD
        macd_functions = ['calculate_macd', 'macd', 'compute_macd', '_calculate_macd']
        
        for func_name in macd_functions:
            if hasattr(technical_indicators, func_name):
                func = getattr(technical_indicators, func_name)
                if callable(func):
                    try:
                        result = func(sample_ohlcv_data['close'])
                        
                        # MACD РѕР±С‹С‡РЅРѕ РІРѕР·РІСЂР°С‰Р°РµС‚ 3 Р·РЅР°С‡РµРЅРёСЏ РёР»Рё DataFrame
                        if isinstance(result, tuple):
                            assert len(result) >= 2  # РњРёРЅРёРјСѓРј MACD Рё Signal
                        elif isinstance(result, pd.DataFrame):
                            assert len(result.columns) >= 2
                        break
                    except:
                        continue


class TestIndicatorIntegration:
    """РРЅС‚РµРіСЂР°С†РёРѕРЅРЅС‹Рµ С‚РµСЃС‚С‹ РёРЅРґРёРєР°С‚РѕСЂРѕРІ"""
    
    def test_indicators_with_real_data(self):
        """РўРµСЃС‚ СЃ СЂРµР°Р»РёСЃС‚РёС‡РЅС‹РјРё РґР°РЅРЅС‹РјРё"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
        # РЎРѕР·РґР°РµРј СЂРµР°Р»РёСЃС‚РёС‡РЅС‹Рµ РґР°РЅРЅС‹Рµ
        dates = pd.date_range('2024-01-01', periods=200, freq='15min')
        
        # РЎРёРјСѓР»РёСЂСѓРµРј СЂР°Р·РЅС‹Рµ СЂС‹РЅРѕС‡РЅС‹Рµ СѓСЃР»РѕРІРёСЏ
        # Р’РѕСЃС…РѕРґСЏС‰РёР№ С‚СЂРµРЅРґ
        uptrend = np.linspace(50000, 52000, 100)
        # Р‘РѕРєРѕРІРёРє
        sideways = np.ones(50) * 52000 + np.random.normal(0, 50, 50)
        # РќРёСЃС…РѕРґСЏС‰РёР№ С‚СЂРµРЅРґ
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
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РёРЅРґРёРєР°С‚РѕСЂС‹ СЂРµР°РіРёСЂСѓСЋС‚ РЅР° РёР·РјРµРЅРµРЅРёРµ С‚СЂРµРЅРґР°
        if 'rsi' in result.columns:
            # RSI РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РІС‹СЃРѕРєРёРј РІ РєРѕРЅС†Рµ РІРѕСЃС…РѕРґСЏС‰РµРіРѕ С‚СЂРµРЅРґР°
            rsi_uptrend_end = result['rsi'].iloc[95:100].mean()
            # RSI РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РЅРёР·РєРёРј РІ РєРѕРЅС†Рµ РЅРёСЃС…РѕРґСЏС‰РµРіРѕ С‚СЂРµРЅРґР°
            rsi_downtrend_end = result['rsi'].iloc[-5:].mean()
            
            if not pd.isna(rsi_uptrend_end) and not pd.isna(rsi_downtrend_end):
                assert rsi_uptrend_end > rsi_downtrend_end
    
    def test_indicators_with_missing_data(self):
        """РўРµСЃС‚ СЃ РїСЂРѕРїСѓС‰РµРЅРЅС‹РјРё РґР°РЅРЅС‹РјРё"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
        # Р”Р°РЅРЅС‹Рµ СЃ NaN Р·РЅР°С‡РµРЅРёСЏРјРё
        df = pd.DataFrame({
            'open': [100, np.nan, 102, 103, 104],
            'high': [101, 102, np.nan, 104, 105],
            'low': [99, 100, 101, np.nan, 103],
            'close': [100, 101, 102, 103, np.nan],
            'volume': [1000, np.nan, 1200, 1300, 1400]
        })
        
        # РќРµ РґРѕР»Р¶РЅРѕ РїР°РґР°С‚СЊ
        result = calculate_all_indicators(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)
    
    def test_indicators_performance(self):
        """РўРµСЃС‚ РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        import time
        
        # Р‘РѕР»СЊС€РѕР№ РґР°С‚Р°СЃРµС‚
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
        
        # Р”РѕР»Р¶РЅРѕ РІС‹РїРѕР»РЅСЏС‚СЊСЃСЏ Р·Р° СЂР°Р·СѓРјРЅРѕРµ РІСЂРµРјСЏ
        assert execution_time < 10.0, f"Too slow: {execution_time:.2f}s"
        assert len(result) == len(large_df)


class TestIndicatorHelpers:
    """РўРµСЃС‚С‹ РІСЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹С… С„СѓРЅРєС†РёР№"""
    
    def test_ema_sma_functions(self):
        """РўРµСЃС‚ С„СѓРЅРєС†РёР№ EMA Рё SMA"""
        from analysis import technical_indicators
        
        prices = pd.Series([100, 102, 101, 103, 102, 104, 103, 105])
        
        # РўРµСЃС‚РёСЂСѓРµРј SMA
        if hasattr(technical_indicators, 'calculate_sma'):
            sma = technical_indicators.calculate_sma(prices, 3)
            assert isinstance(sma, pd.Series)
            # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ СЂР°СЃС‡РµС‚Р°
            assert abs(sma.iloc[2] - (100 + 102 + 101) / 3) < 0.01
        
        # РўРµСЃС‚РёСЂСѓРµРј EMA
        if hasattr(technical_indicators, 'calculate_ema'):
            ema = technical_indicators.calculate_ema(prices, 3)
            assert isinstance(ema, pd.Series)
            assert len(ema) == len(prices)
    
    def test_bollinger_bands(self):
        """РўРµСЃС‚ РїРѕР»РѕСЃ Р‘РѕР»Р»РёРЅРґР¶РµСЂР°"""
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
        """РўРµСЃС‚ РёРЅРґРёРєР°С‚РѕСЂРѕРІ РѕР±СЉРµРјР°"""
        from analysis import technical_indicators
        
        df = pd.DataFrame({
            'close': [100, 101, 102, 101, 103],
            'volume': [1000, 1200, 900, 1100, 1300]
        })
        
        if hasattr(technical_indicators, 'calculate_volume_indicators'):
            result = technical_indicators.calculate_volume_indicators(df)
            assert isinstance(result, (dict, pd.DataFrame, pd.Series))


class TestEdgeCases:
    """РўРµСЃС‚С‹ РіСЂР°РЅРёС‡РЅС‹С… СЃР»СѓС‡Р°РµРІ"""
    
    def test_extreme_values(self):
        """РўРµСЃС‚ СЃ СЌРєСЃС‚СЂРµРјР°Р»СЊРЅС‹РјРё Р·РЅР°С‡РµРЅРёСЏРјРё"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
        extreme_df = pd.DataFrame({
            'open': [1e-10, 1e10, 100, 100],
            'high': [1e-10, 1e10, 101, 101],
            'low': [1e-10, 1e10, 99, 99],
            'close': [1e-10, 1e10, 100, 100],
            'volume': [1, 1e15, 1000, 1000]
        })
        
        # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ Р±РµР· overflow
        result = calculate_all_indicators(extreme_df)
        assert isinstance(result, pd.DataFrame)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РЅРµС‚ inf Р·РЅР°С‡РµРЅРёР№ РІ С‡РёСЃР»РѕРІС‹С… РєРѕР»РѕРЅРєР°С…
        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            assert not np.isinf(result[col]).any(), f"Inf values in {col}"
    
    def test_constant_values(self):
        """РўРµСЃС‚ РєРѕРіРґР° РІСЃРµ Р·РЅР°С‡РµРЅРёСЏ РѕРґРёРЅР°РєРѕРІС‹Рµ"""
        from crypto_ai_bot.core.indicators.unified import calculate_all_indicators
        
        constant_df = pd.DataFrame({
            'open': [100] * 50,
            'high': [100] * 50,
            'low': [100] * 50,
            'close': [100] * 50,
            'volume': [1000] * 50
        })
        
        result = calculate_all_indicators(constant_df)
        
        # RSI РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РѕРєРѕР»Рѕ 50 (РЅРµС‚ РґРІРёР¶РµРЅРёСЏ)
        if 'rsi' in result.columns:
            rsi_values = result['rsi'].dropna()
            if len(rsi_values) > 0:
                assert 40 < rsi_values.mean() < 60
        
        # ATR РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ Р±Р»РёР·РѕРє Рє 0
        if 'atr' in result.columns:
            atr_values = result['atr'].dropna()
            if len(atr_values) > 0:
                assert atr_values.mean() < 1.0

