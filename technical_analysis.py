import ccxt
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.volatility import BollingerBands
from ta.volume import OnBalanceVolumeIndicator
from utils import detect_support_resistance
import logging

logger = logging.getLogger(__name__)

class AdvancedCandlestickPatterns:
    @staticmethod
    def is_doji(candle, threshold=0.1):
        """Doji - тело свечи очень маленькое"""
        body = abs(candle['close'] - candle['open'])
        range_candle = candle['high'] - candle['low']
        return body / range_candle < threshold if range_candle > 0 else False
    
    @staticmethod
    def is_hammer(candle):
        """Hammer - длинная нижняя тень, короткая верхняя"""
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        range_candle = candle['high'] - candle['low']
        
        if range_candle == 0:
            return False
            
        return (
            lower_shadow > 2 * body and
            upper_shadow < body * 0.5 and
            lower_shadow > 0.6 * range_candle
        )
    
    @staticmethod
    def is_shooting_star(candle):
        """Shooting Star - длинная верхняя тень, короткая нижняя"""
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        range_candle = candle['high'] - candle['low']
        
        if range_candle == 0:
            return False
            
        return (
            upper_shadow > 2 * body and
            lower_shadow < body * 0.5 and
            upper_shadow > 0.6 * range_candle
        )
    
    @staticmethod
    def is_spinning_top(candle):
        """Spinning Top - маленькое тело, длинные тени с обеих сторон"""
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        range_candle = candle['high'] - candle['low']
        
        if range_candle == 0:
            return False
            
        return (
            body < 0.3 * range_candle and
            lower_shadow > body and
            upper_shadow > body
        )
    
    @staticmethod
    def is_marubozu(candle):
        """Marubozu - нет теней или очень маленькие"""
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        range_candle = candle['high'] - candle['low']
        
        if range_candle == 0:
            return False
            
        return (
            body > 0.95 * range_candle and
            lower_shadow < 0.025 * range_candle and
            upper_shadow < 0.025 * range_candle
        )

def identify_advanced_patterns(df):
    """Продвинутое определение паттернов свечей"""
    if len(df) < 3:
        return {"pattern": "INSUFFICIENT_DATA", "strength": 0, "direction": "NEUTRAL"}
    
    patterns = AdvancedCandlestickPatterns()
    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3] if len(df) >= 3 else None
    
    pattern_found = "NONE"
    strength = 0
    direction = "NEUTRAL"
    
    # Одиночные паттерны
    if patterns.is_doji(last):
        pattern_found = "DOJI"
        strength = 3
        direction = "REVERSAL"
        
    elif patterns.is_hammer(last):
        pattern_found = "HAMMER" 
        strength = 4
        direction = "BULLISH"
        
    elif patterns.is_shooting_star(last):
        pattern_found = "SHOOTING_STAR"
        strength = 4
        direction = "BEARISH"
        
    elif patterns.is_spinning_top(last):
        pattern_found = "SPINNING_TOP"
        strength = 2
        direction = "INDECISION"
        
    elif patterns.is_marubozu(last):
        if last['close'] > last['open']:
            pattern_found = "BULLISH_MARUBOZU"
            direction = "BULLISH"
        else:
            pattern_found = "BEARISH_MARUBOZU" 
            direction = "BEARISH"
        strength = 5
    
    # Двухсвечные паттерны
    if pattern_found == "NONE":
        # Engulfing patterns
        if (last['close'] > last['open'] and prev['close'] < prev['open'] and 
            last['close'] > prev['open'] and last['open'] < prev['close'] and
            abs(last['close'] - last['open']) > abs(prev['close'] - prev['open']) * 1.3):
            pattern_found = "BULLISH_ENGULFING"
            strength = 5
            direction = "BULLISH"
            
        elif (last['close'] < last['open'] and prev['close'] > prev['open'] and 
              last['close'] < prev['open'] and last['open'] > prev['close'] and
              abs(last['close'] - last['open']) > abs(prev['close'] - prev['open']) * 1.3):
            pattern_found = "BEARISH_ENGULFING"
            strength = 5
            direction = "BEARISH"
            
        # Harami patterns
        elif (prev['close'] < prev['open'] and last['close'] > last['open'] and
              last['open'] > prev['close'] and last['close'] < prev['open']):
            pattern_found = "BULLISH_HARAMI"
            strength = 3
            direction = "BULLISH"
            
        elif (prev['close'] > prev['open'] and last['close'] < last['open'] and
              last['open'] < prev['close'] and last['close'] > prev['open']):
            pattern_found = "BEARISH_HARAMI"
            strength = 3
            direction = "BEARISH"
            
        # Piercing Line / Dark Cloud Cover
        elif (prev['close'] < prev['open'] and last['close'] > last['open'] and
              last['open'] < prev['low'] and last['close'] > (prev['open'] + prev['close']) / 2):
            pattern_found = "PIERCING_LINE"
            strength = 4
            direction = "BULLISH"
            
        elif (prev['close'] > prev['open'] and last['close'] < last['open'] and
              last['open'] > prev['high'] and last['close'] < (prev['open'] + prev['close']) / 2):
            pattern_found = "DARK_CLOUD_COVER"
            strength = 4
            direction = "BEARISH"
    
    # Трёхсвечные паттерны
    if pattern_found == "NONE" and prev2 is not None:
        # Morning Star
        if (prev2['close'] < prev2['open'] and  # Первая - медвежья
            patterns.is_doji(prev) and           # Вторая - doji/маленькая
            last['close'] > last['open'] and     # Третья - бычья
            last['close'] > (prev2['open'] + prev2['close']) / 2):
            pattern_found = "MORNING_STAR"
            strength = 6
            direction = "BULLISH"
            
        # Evening Star
        elif (prev2['close'] > prev2['open'] and  # Первая - бычья
              patterns.is_doji(prev) and          # Вторая - doji/маленькая
              last['close'] < last['open'] and    # Третья - медвежья
              last['close'] < (prev2['open'] + prev2['close']) / 2):
            pattern_found = "EVENING_STAR"
            strength = 6
            direction = "BEARISH"
            
        # Three White Soldiers
        elif (all([candle['close'] > candle['open'] for candle in [prev2, prev, last]]) and
              prev['close'] > prev2['close'] and last['close'] > prev['close'] and
              all([abs(candle['close'] - candle['open']) > (candle['high'] - candle['low']) * 0.6 
                   for candle in [prev2, prev, last]])):
            pattern_found = "THREE_WHITE_SOLDIERS"
            strength = 6
            direction = "BULLISH"
            
        # Three Black Crows
        elif (all([candle['close'] < candle['open'] for candle in [prev2, prev, last]]) and
              prev['close'] < prev2['close'] and last['close'] < prev['close'] and
              all([abs(candle['close'] - candle['open']) > (candle['high'] - candle['low']) * 0.6 
                   for candle in [prev2, prev, last]])):
            pattern_found = "THREE_BLACK_CROWS"
            strength = 6
            direction = "BEARISH"
    
    return {
        "pattern": pattern_found,
        "strength": strength,
        "direction": direction
    }

def calculate_pattern_score(pattern_data, rsi, stoch_rsi):
    """Вычисляет итоговый балл паттерна с учётом индикаторов"""
    base_score = pattern_data["strength"]
    
    # Усиливаем сигнал если индикаторы подтверждают
    if pattern_data["direction"] == "BULLISH" and rsi < 40 and stoch_rsi < 30:
        base_score *= 1.5
    elif pattern_data["direction"] == "BEARISH" and rsi > 60 and stoch_rsi > 70:
        base_score *= 1.5
    elif pattern_data["direction"] == "REVERSAL":
        if (rsi > 70 or rsi < 30) or (stoch_rsi > 80 or stoch_rsi < 20):
            base_score *= 1.3
            
    return min(base_score, 10)  # Максимум 10 баллов

def generate_signal():
    try:
        exchange = ccxt.gateio()
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe="15m", limit=100)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # Индикаторы
        df["rsi"] = RSIIndicator(close=df["close"]).rsi()
        
        macd = MACD(close=df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        
        df["ema_9"] = EMAIndicator(close=df["close"], window=9).ema_indicator()
        df["ema_21"] = EMAIndicator(close=df["close"], window=21).ema_indicator()
        
        bollinger = BollingerBands(close=df["close"], window=20, window_dev=2)
        df["bb_upper"] = bollinger.bollinger_hband()
        df["bb_lower"] = bollinger.bollinger_lband()
        
        df["adx"] = ADXIndicator(high=df["high"], low=df["low"], close=df["close"]).adx()
        df["obv"] = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"]).on_balance_volume()
        
        df["stoch_rsi"] = StochasticOscillator(
            high=df["high"], 
            low=df["low"], 
            close=df["close"]
        ).stoch()
        
        # Последние значения
        current_rsi = df["rsi"].iloc[-1]
        current_macd = df["macd"].iloc[-1] 
        current_macd_signal = df["macd_signal"].iloc[-1]
        current_price = df["close"].iloc[-1]
        ema9 = df["ema_9"].iloc[-1]
        ema21 = df["ema_21"].iloc[-1]
        bb_upper = df["bb_upper"].iloc[-1]
        bb_lower = df["bb_lower"].iloc[-1]
        stoch_rsi = df["stoch_rsi"].iloc[-1]
        adx = df["adx"].iloc[-1]
        
        # Продвинутое определение паттернов
        pattern_data = identify_advanced_patterns(df)
        pattern_score = calculate_pattern_score(pattern_data, current_rsi, stoch_rsi)
        
        # Уровни поддержки/сопротивления
        try:
            support, resistance = detect_support_resistance(df)
        except Exception as e:
            logger.warning(f"Ошибка при определении уровней: {e}")
            support, resistance = current_price * 0.98, current_price * 1.02
        
        # Улучшенная сигнальная логика
        signal = "HOLD"
        confidence = 0
        
        # BUY сигналы
        buy_conditions = [
            not pd.isna(current_rsi) and current_rsi < 35,  # Oversold
            not pd.isna(current_macd) and not pd.isna(current_macd_signal) and current_macd > current_macd_signal,
            not pd.isna(ema9) and not pd.isna(ema21) and ema9 > ema21,  # Uptrend
            not pd.isna(bb_lower) and current_price < bb_lower * 1.005,  # Near lower band
            not pd.isna(stoch_rsi) and stoch_rsi < 25,  # Stoch oversold
            pattern_data["direction"] in ["BULLISH", "REVERSAL"] and pattern_score >= 4,
            not pd.isna(adx) and adx > 25,  # Strong trend
            current_price > support * 0.995  # Above support
        ]
        
        # SELL сигналы
        sell_conditions = [
            not pd.isna(current_rsi) and current_rsi > 65,  # Overbought
            not pd.isna(current_macd) and not pd.isna(current_macd_signal) and current_macd < current_macd_signal,
            not pd.isna(ema9) and not pd.isna(ema21) and ema9 < ema21,  # Downtrend
            not pd.isna(bb_upper) and current_price > bb_upper * 0.995,  # Near upper band
            not pd.isna(stoch_rsi) and stoch_rsi > 75,  # Stoch overbought
            pattern_data["direction"] == "BEARISH" and pattern_score >= 4,
            not pd.isna(adx) and adx > 25,  # Strong trend
            current_price < resistance * 1.005  # Below resistance
        ]
        
        buy_score = sum(buy_conditions)
        sell_score = sum(sell_conditions)
        
        if buy_score >= 5:
            signal = "STRONG_BUY"
            confidence = min(buy_score * 12.5, 100)
        elif buy_score >= 3:
            signal = "BUY"
            confidence = buy_score * 15
        elif sell_score >= 5:
            signal = "STRONG_SELL"
            confidence = min(sell_score * 12.5, 100)
        elif sell_score >= 3:
            signal = "SELL"
            confidence = sell_score * 15
        
        logger.info(f"📈 RSI: {current_rsi:.2f}, MACD: {current_macd:.4f}, EMA9/21: {ema9:.2f}/{ema21:.2f}")
        logger.info(f"📊 Bollinger: [{bb_lower:.2f}, {bb_upper:.2f}], Stoch: {stoch_rsi:.2f}, ADX: {adx:.2f}")
        logger.info(f"🕯️ Pattern: {pattern_data['pattern']} (Score: {pattern_score:.1f}, Dir: {pattern_data['direction']})")
        logger.info(f"💰 Support: {support:.2f}, Resistance: {resistance:.2f}")
        logger.info(f"📢 Сигнал: {signal} (Confidence: {confidence:.1f}%)")
        
        return {
            "signal": signal,
            "confidence": confidence,
            "rsi": current_rsi,
            "macd": current_macd,
            "pattern": pattern_data['pattern'],
            "pattern_score": pattern_score,
            "pattern_direction": pattern_data['direction'],
            "price": current_price,
            "support": support,
            "resistance": resistance,
            "buy_score": buy_score,
            "sell_score": sell_score
        }
        
    except Exception as e:
        logger.error(f"Ошибка в generate_signal: {e}")
        return {
            "signal": "ERROR",
            "confidence": 0,
            "rsi": 0,
            "macd": 0,
            "pattern": "ERROR",
            "pattern_score": 0,
            "pattern_direction": "NEUTRAL",
            "price": 0,
            "support": 0,
            "resistance": 0,
            "buy_score": 0,
            "sell_score": 0
        }
