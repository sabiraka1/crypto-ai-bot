import ccxt
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.volatility import BollingerBands
from ta.utils import dropna
from datetime import datetime
import warnings

warnings.filterwarnings("ignore")

exchange = ccxt.gateio()
symbol = "BTC/USDT"
timeframe = "15m"
limit = 100

rsi_history = []  # Для отслеживания RSI > 70 в течение 90 минут


def fetch_ohlcv():
    data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def detect_candle_pattern(df):
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"])
    range_ = last["high"] - last["low"]
    upper_shadow = last["high"] - max(last["close"], last["open"])
    lower_shadow = min(last["close"], last["open"]) - last["low"]

    if body < range_ * 0.2 and upper_shadow > body and lower_shadow > body:
        return "doji"
    if lower_shadow > body * 2 and last["close"] > last["open"]:
        return "hammer"
    if upper_shadow > body * 2 and last["close"] < last["open"]:
        return "shooting_star"
    if last["close"] > last["open"] and df.iloc[-2]["close"] < df.iloc[-2]["open"] and last["open"] < df.iloc[-2]["close"] and last["close"] > df.iloc[-2]["open"]:
        return "engulfing_bullish"
    if last["close"] < last["open"] and df.iloc[-2]["close"] > df.iloc[-2]["open"] and last["open"] > df.iloc[-2]["close"] and last["close"] < df.iloc[-2]["open"]:
        return "engulfing_bearish"
    if upper_shadow < body * 0.2 and lower_shadow > body * 2:
        return "hanging_man"
    return None


def generate_signal():
    df = fetch_ohlcv()
    df = dropna(df)

    rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
    macd = MACD(df["close"]).macd_diff().iloc[-1]
    ema_fast = EMAIndicator(df["close"], window=9).ema_indicator().iloc[-1]
    ema_slow = EMAIndicator(df["close"], window=21).ema_indicator().iloc[-1]
    bollinger = BollingerBands(df["close"])
    bb_upper = bollinger.bollinger_hband().iloc[-1]
    bb_lower = bollinger.bollinger_lband().iloc[-1]
    adx = ADXIndicator(df["high"], df["low"], df["close"]).adx().iloc[-1]
    stoch_rsi = StochasticOscillator(df["close"]).stoch().iloc[-1]

    price = df["close"].iloc[-1]
    pattern = detect_candle_pattern(df)

    # === EMA сигнал ===
    if ema_fast > ema_slow:
        ema_signal = "bullish"
    elif ema_fast < ema_slow:
        ema_signal = "bearish"
    else:
        ema_signal = "neutral"

    # === Bollinger позиция ===
    if price < bb_lower:
        bollinger_position = "low"
    elif price > bb_upper:
        bollinger_position = "high"
    else:
        bollinger_position = "middle"

    # === Историческое наблюдение за RSI ===
    rsi_history.append(rsi)
    if len(rsi_history) > 6:
        rsi_history.pop(0)
    rsi_overbought_too_long = all(r > 70 for r in rsi_history)

    # === Принятие решения ===
    if rsi_overbought_too_long:
        signal = "SELL"
    elif rsi < 30 and macd > 0 and ema_fast > ema_slow and price < bb_lower and adx > 20:
        signal = "BUY"
    elif rsi > 70 and macd < 0 and ema_fast < ema_slow and price > bb_upper and adx > 20:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "signal": signal,
        "rsi": round(rsi, 2),
        "macd": round(macd, 2),
        "pattern": pattern,
        "price": round(price, 2),
        "ema_signal": ema_signal,
        "bollinger": bollinger_position,
        "adx": round(adx, 2),
        "stochrsi": round(stoch_rsi, 2),
        "patterns": [pattern] if pattern else []
    }
