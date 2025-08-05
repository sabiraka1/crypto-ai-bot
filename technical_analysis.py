import ccxt
import pandas as pd
import ta
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GATE_API_KEY")
api_secret = os.getenv("GATE_API_SECRET")

exchange = ccxt.gateio({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
})

symbol = 'BTC/USDT'

def fetch_ohlcv():
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def generate_signal():
    df = fetch_ohlcv()
    df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
    df['macd'] = ta.trend.MACD(df['close']).macd_diff()

    latest = df.iloc[-1]
    price = latest['close']
    rsi = latest['rsi']
    macd = latest['macd']

    if rsi < 30 and macd > 0:
        signal = 'BUY'
    elif rsi > 70 and macd < 0:
        signal = 'SELL'
    else:
        signal = 'HOLD'

    return {
        'signal': signal,
        'rsi': round(rsi, 2),
        'macd': round(macd, 4),
        'price': round(price, 2)
    }
