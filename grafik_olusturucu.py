import ccxt
import pandas as pd
import matplotlib.pyplot as plt
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

def plot_indicators():
    df = fetch_ohlcv()
    df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
    df['macd'] = ta.trend.MACD(df['close']).macd()
    df['macd_signal'] = ta.trend.MACD(df['close']).macd_signal()

    plt.figure(figsize=(12, 8))

    # Цена
    plt.subplot(3, 1, 1)
    plt.plot(df['timestamp'], df['close'], label='Price')
    plt.title("Price")

    # RSI
    plt.subplot(3, 1, 2)
    plt.plot(df['timestamp'], df['rsi'], label='RSI', color='orange')
    plt.axhline(70, color='red', linestyle='--')
    plt.axhline(30, color='green', linestyle='--')
    plt.title("RSI")

    # MACD
    plt.subplot(3, 1, 3)
    plt.plot(df['timestamp'], df['macd'], label='MACD', color='blue')
    plt.plot(df['timestamp'], df['macd_signal'], label='Signal', color='red')
    plt.title("MACD")
    plt.tight_layout()

    file_path = "chart.png"
    plt.savefig(file_path)
    plt.close()
    return file_path
