import pandas as pd
import numpy as np
from typing import Tuple

class TechnicalIndicators:
    """Расчет технических индикаторов"""
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Расчет RSI"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Расчет MACD"""
        ema_fast = df['close'].ewm(span=fast).mean()
        ema_slow = df['close'].ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal).mean()
        macd_histogram = macd - macd_signal
        return macd, macd_signal, macd_histogram
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Расчет полос Боллинджера"""
        sma = df['close'].rolling(window=period).mean()
        std_dev = df['close'].rolling(window=period).std()
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        return upper, sma, lower
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
        """Расчет EMA"""
        return df['close'].ewm(span=period).mean()
    
    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """Расчет Стохастика"""
        low_min = df['low'].rolling(window=k_period).min()
        high_max = df['high'].rolling(window=k_period).max()
        k = 100 * ((df['close'] - low_min) / (high_max - low_min))
        d = k.rolling(window=d_period).mean()
        return k, d
    
    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Расчет ADX"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        true_range = np.maximum(high_low, np.maximum(high_close, low_close))
        atr = true_range.rolling(window=period).mean()
        
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
        
        plus_di = 100 * (pd.Series(plus_dm).rolling(window=period).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm).rolling(window=period).mean() / atr)
        
        dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        adx = dx.rolling(window=period).mean()
        
        return adx
    
    @staticmethod
    def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Расчет всех индикаторов"""
        df = df.copy()
        
        # RSI
        df['rsi'] = TechnicalIndicators.calculate_rsi(df)
        
        # MACD
        df['macd'], df['macd_signal'], df['macd_histogram'] = TechnicalIndicators.calculate_macd(df)
        
        # Bollinger Bands
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = TechnicalIndicators.calculate_bollinger_bands(df)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        # EMA
        df['ema_9'] = TechnicalIndicators.calculate_ema(df, 9)
        df['ema_21'] = TechnicalIndicators.calculate_ema(df, 21)
        df['ema_cross'] = (df['ema_9'] - df['ema_21']) / df['ema_21']
        
        # Stochastic
        df['stoch_k'], df['stoch_d'] = TechnicalIndicators.calculate_stochastic(df)
        
        # ADX
        df['adx'] = TechnicalIndicators.calculate_adx(df)
        
        # Volume indicators
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        return df