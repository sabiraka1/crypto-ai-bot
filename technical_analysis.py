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

def identify_simple_pattern(df):
    """Простая функция для определения базовых паттернов свечей"""
    if len(df) < 2:
        return "NONE"
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # Doji pattern
    body = abs(last['close'] - last['open'])
    range_candle = last['high'] - last['low']
    
    if body / range_candle < 0.1:
        return "DOJI"
    
    # Hammer pattern
    if last['close'] > last['open']:  # Bullish candle
        lower_shadow = last['open'] - last['low']
        upper_shadow = last['high'] - last['close']
        if lower_shadow > 2 * body and upper_shadow < body * 0.5:
            return "HAMMER"
    
    # Shooting star pattern
    if last['open'] > last['close']:  # Bearish candle
        upper_shadow = last['high'] - last['open']
        lower_shadow = last['close'] - last['low']
        if upper_shadow > 2 * body and lower_shadow < body * 0.5:
            return "SHOOTING_STAR"
    
    # Engulfing patterns
    if (last['close'] > last['open'] and prev['close'] < prev['open'] and 
        last['close'] > prev['open'] and last['open'] < prev['close']):
        return "BULLISH_ENGULFING"
    
    if (last['close'] < last['open'] and prev['close'] > prev['open'] and 
        last['close'] < prev['open'] and last['open'] > prev['close']):
        return "BEARISH_ENGULFING"
    
    return "NONE"

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
        
        # Исправленный StochasticOscillator
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
        
        # Простое определение паттерна свечей
        pattern = identify_simple_pattern(df)
        
        # Уровни поддержки/сопротивления
        try:
            support, resistance = detect_support_resistance(df)
        except Exception as e:
            logger.warning(f"Ошибка при определении уровней поддержки/сопротивления: {e}")
            support, resistance = current_price * 0.98, current_price * 1.02
        
        # Сигнальная логика с проверкой NaN
        signal = "HOLD"
        
        # Проверяем на NaN значения перед сравнением
        if (
            not pd.isna(current_rsi) and current_rsi < 30
            and not pd.isna(current_macd) and not pd.isna(current_macd_signal) and current_macd > current_macd_signal
            and not pd.isna(ema9) and not pd.isna(ema21) and ema9 > ema21
            and not pd.isna(bb_lower) and current_price < bb_lower
            and not pd.isna(stoch_rsi) and stoch_rsi < 20
        ):
            signal = "BUY"
        elif (
            not pd.isna(current_rsi) and current_rsi > 70
            and not pd.isna(current_macd) and not pd.isna(current_macd_signal) and current_macd < current_macd_signal
            and not pd.isna(ema9) and not pd.isna(ema21) and ema9 < ema21
            and not pd.isna(bb_upper) and current_price > bb_upper
            and not pd.isna(stoch_rsi) and stoch_rsi > 80
        ):
            signal = "SELL"
        
        logger.info(f"📈 RSI: {current_rsi:.2f}, MACD: {current_macd:.2f}, EMA9: {ema9:.2f}, EMA21: {ema21:.2f}")
        logger.info(f"📊 Bollinger: [{bb_lower:.2f}, {bb_upper:.2f}], Stoch RSI: {stoch_rsi:.2f}")
        logger.info(f"🕯️ Pattern: {pattern}, Support: {support}, Resistance: {resistance}")
        logger.info(f"📢 Сигнал: {signal}")
        
        return {
            "signal": signal,
            "rsi": current_rsi,
            "macd": current_macd,
            "pattern": pattern,
            "price": current_price
        }
        
    except Exception as e:
        logger.error(f"Ошибка в generate_signal: {e}")
        return {
            "signal": "ERROR",
            "rsi": 0,
            "macd": 0,
            "pattern": "ERROR",
            "price": 0
        }
