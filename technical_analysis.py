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
import matplotlib.pyplot as plt

def draw_rsi_macd_chart(signal_data):
    df = fetch_ohlcv()
    df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    # Цены
    ax1.plot(df['timestamp'], df['close'], label='Price', linewidth=1.5)
    ax1.set_title(f"Candlestick + RSI/MACD — Сигнал: {signal_data['signal']}")
    ax1.legend()
    ax1.grid(True)

    # RSI
    ax1b = ax1.twinx()
    ax1b.plot(df['timestamp'], df['rsi'], color='purple', alpha=0.3, label='RSI')
    ax1b.axhline(70, color='red', linestyle='--', linewidth=0.7)
    ax1b.axhline(30, color='green', linestyle='--', linewidth=0.7)
    ax1b.set_ylim(0, 100)
    ax1b.legend(loc='upper right')

    # MACD
    ax2.plot(df['timestamp'], df['macd'], label='MACD', color='blue')
    ax2.plot(df['timestamp'], df['macd_signal'], label='Signal', color='orange')
    ax2.axhline(0, color='gray', linewidth=0.7)
    ax2.legend()
    ax2.grid(True)

    # Сохраняем график
    output_path = 'charts/chart.png'
    os.makedirs('charts', exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

    return output_path
