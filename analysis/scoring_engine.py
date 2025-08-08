import pandas as pd
import numpy as np
from typing import Tuple
from config.settings import MarketCondition, TradingConfig
import logging

class ScoringEngine:
    """MACD балльная система принятия решений"""
    
    def __init__(self):
        self.market_modifiers = {
            MarketCondition.STRONG_BULL: 0.8,
            MarketCondition.WEAK_BULL: 0.9,
            MarketCondition.SIDEWAYS: 1.0,
            MarketCondition.WEAK_BEAR: 1.4,
            MarketCondition.STRONG_BEAR: 1.5
        }
    
    def calculate_buy_score(self, df: pd.DataFrame, market_condition: MarketCondition, ai_confidence: float = 0.5) -> Tuple[float, dict]:
        """Расчет балла для покупки"""
        try:
            # Базовые MACD баллы
            macd_score = self._calculate_macd_score(df)
            
            # AI модификатор
            ai_modifier = self._calculate_ai_modifier(ai_confidence)
            
            # Рыночный модификатор
            market_modifier = self.market_modifiers.get(market_condition, 1.0)
            
            # Итоговый балл
            base_score = macd_score + ai_modifier
            final_score = base_score
            threshold = TradingConfig.MIN_SCORE_TO_BUY * market_modifier
            
            details = {
                "macd_score": macd_score,
                "ai_modifier": ai_modifier,
                "market_modifier": market_modifier,
                "threshold": threshold,
                "market_condition": market_condition.value
            }
            
            logging.info(f"📊 Buy Score: {final_score:.2f}/{threshold:.2f} | MACD: {macd_score} | AI: {ai_modifier:.2f}")
            
            return final_score, details
            
        except Exception as e:
            logging.error(f"Scoring calculation failed: {e}")
            return 0.0, {}
    
    def _calculate_macd_score(self, df: pd.DataFrame) -> float:
        """Расчет MACD баллов (0-3)"""
        if len(df) < 5:
            return 0.0
        
        score = 0.0
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        
        # 1. Пересечение MACD > Signal = 1 балл
        if (latest['macd'] > latest['macd_signal'] and 
            previous['macd'] <= previous['macd_signal']):
            score += 1.0
            logging.info("✅ MACD Crossover detected (+1 point)")
        
        # 2. Растущая гистограмма = +1 балл
        if (latest['macd_histogram'] > previous['macd_histogram'] and
            latest['macd_histogram'] > 0):
            score += 1.0
            logging.info("✅ MACD Histogram growing (+1 point)")
        
        # 3. RSI поддержка = +1 балл
        if 30 <= latest['rsi'] <= 70:
            score += 1.0
            logging.info("✅ RSI in healthy range (+1 point)")
        
        return score
    
    def _calculate_ai_modifier(self, ai_confidence: float) -> float:
        """Расчет AI модификатора"""
        if ai_confidence > 0.8:
            return 1.0
        elif ai_confidence > 0.6:
            return 0.5
        elif ai_confidence < 0.4:
            return -0.5
        else:
            return 0.0
    
    def should_sell(self, df: pd.DataFrame, position_profit_pct: float, candles_rsi_over_70: int) -> Tuple[bool, str]:
        """Определение необходимости продажи"""
        latest = df.iloc[-1]
        
        # Обязательные условия продажи
        if position_profit_pct >= TradingConfig.TAKE_PROFIT_PCT:
            return True, f"Take Profit reached: {position_profit_pct:.2f}%"
        
        if position_profit_pct <= -TradingConfig.STOP_LOSS_PCT:
            return True, f"Stop Loss triggered: {position_profit_pct:.2f}%"
        
        if latest['rsi'] >= TradingConfig.RSI_CRITICAL:
            return True, f"Critical RSI level: {latest['rsi']:.1f}"
        
        if candles_rsi_over_70 >= TradingConfig.RSI_CLOSE_CANDLES:
            return True, f"RSI >70 for {candles_rsi_over_70} candles"
        
        return False, "No sell signal"