import pandas as pd
import numpy as np
from typing import Tuple
from config.settings import MarketCondition
import logging

class MultiTimeframeAnalyzer:
    """Анализ рынка на разных таймфреймах"""
    
    def __init__(self):
        self.timeframes = {
            "1d": {"weight": 0.6, "period": 24},
            "4h": {"weight": 0.4, "period": 6}
        }
    
    def analyze_market_condition(self, df_1d: pd.DataFrame, df_4h: pd.DataFrame) -> Tuple[MarketCondition, float]:
        """Определение состояния рынка"""
        try:
            # Анализ дневного тренда
            daily_trend = self._analyze_trend(df_1d)
            daily_strength = self._analyze_strength(df_1d)
            
            # Анализ 4-часового тренда
            h4_trend = self._analyze_trend(df_4h)
            h4_strength = self._analyze_strength(df_4h)
            
            # Комбинированный анализ
            combined_trend = (daily_trend * 0.6) + (h4_trend * 0.4)
            combined_strength = (daily_strength * 0.6) + (h4_strength * 0.4)
            
            condition = self._classify_market(combined_trend, combined_strength)
            confidence = abs(combined_trend) * combined_strength
            
            logging.info(f"📊 Market Analysis: {condition.value}, Confidence: {confidence:.2f}")
            return condition, confidence
            
        except Exception as e:
            logging.error(f"Market analysis failed: {e}")
            return MarketCondition.SIDEWAYS, 0.5
    
    def _analyze_trend(self, df: pd.DataFrame) -> float:
        """Анализ направления тренда (-1 до 1)"""
        if len(df) < 50:
            return 0.0
        
        # EMA тренд
        ema_20 = df['close'].ewm(span=20).mean()
        ema_50 = df['close'].ewm(span=50).mean()
        ema_trend = (ema_20.iloc[-1] - ema_50.iloc[-1]) / ema_50.iloc[-1]
        
        # Ценовой моментум
        price_momentum = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
        
        # Объемный тренд
        volume_ma = df['volume'].rolling(20).mean()
        recent_volume = volume_ma.iloc[-5:].mean()
        old_volume = volume_ma.iloc[-25:-5].mean()
        volume_trend = (recent_volume - old_volume) / old_volume if old_volume > 0 else 0
        
        # Комбинированный тренд
        trend = (ema_trend * 0.4) + (price_momentum * 0.4) + (volume_trend * 0.2)
        return np.clip(trend, -1, 1)
    
    def _analyze_strength(self, df: pd.DataFrame) -> float:
        """Анализ силы тренда (0 до 1)"""
        if len(df) < 20:
            return 0.5
        
        # Волатильность
        returns = df['close'].pct_change().dropna()
        volatility = returns.std()
        
        # ADX для силы тренда
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = np.maximum(high_low, np.maximum(high_close, low_close))
        atr = true_range.rolling(14).mean()
        
        # Нормализация силы
        strength = 1 / (1 + volatility * 100)  # Обратная волатильность
        return np.clip(strength, 0, 1)
    
    def _classify_market(self, trend: float, strength: float) -> MarketCondition:
        """Классификация рыночных условий"""
        if trend > 0.1 and strength > 0.7:
            return MarketCondition.STRONG_BULL
        elif trend > 0.05 and strength > 0.5:
            return MarketCondition.WEAK_BULL
        elif trend < -0.1 and strength > 0.7:
            return MarketCondition.STRONG_BEAR
        elif trend < -0.05 and strength > 0.5:
            return MarketCondition.WEAK_BEAR
        else:
            return MarketCondition.SIDEWAYS