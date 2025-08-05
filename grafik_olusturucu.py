import os
import matplotlib.pyplot as plt
from datetime import datetime
from ta.momentum import RSIIndicator
from ta.trend import MACD
import pandas as pd
import ccxt
from dotenv import load_dotenv

load_dotenv()

# Настройка биржи
exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True
})

def fetch_ohlcv():
    try:
        bars = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Ошибка загрузки OHLCV: {e}")
        return pd.DataFrame()

def draw_rsi_macd_chart(result):
    df = fetch_ohlcv()
    if df.empty or len(df) < 30:
        print("Недостаточно данных для построения графика.")
        return None

    # RSI
    rsi_indicator = RSIIndicator(close=df['close'], window=14)
    df['rsi'] = rsi_indicator.rsi()

    # MACD
    macd = MACD(close=df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    # Последняя строка
    last_row = df.iloc[-1]
    signal = result.get('signal', 'NONE')
    rsi = result.get('rsi', last_row.get('rsi', 0))
    macd_val = result.get('macd', last_row.get('macd', 0))
    pattern = result.get('pattern', '')

    # Построение графиков
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)

    # Цена
    ax1.plot(df['timestamp'], df['close'], label='Close', color='black')
    ax1.set_title(f"📊 Signal: {signal} | Pattern: {pattern}")
    ax1.grid(True)

    # RSI
    ax2.plot(df['timestamp'], df['rsi'], label='RSI', color='blue')
    ax2.axhline(70, color='red', linestyle='--', linewidth=0.8)
    ax2.axhline(30, color='green', linestyle='--', linewidth=0.8)
    ax2.set_title('RSI')
    ax2.grid(True)

    # MACD
    ax3.plot(df['timestamp'], df['macd'], label='MACD', color='purple')
    ax3.plot(df['timestamp'], df['macd_signal'], label='Signal', color='orange')
    ax3.set_title('MACD')
    ax3.legend()
    ax3.grid(True)

    # Аннотация сигнала
    color = 'green' if signal == "BUY" else 'red' if signal == "SELL" else 'gray'
    ax1.annotate(f"{signal}",
                 xy=(last_row['timestamp'], last_row['close']),
                 xytext=(last_row['timestamp'], last_row['close'] + 100),
                 arrowprops=dict(facecolor=color, shrink=0.05),
                 fontsize=10, color=color)

    # Паттерн
    if pattern:
        ax1.text(last_row['timestamp'], last_row['close'] - 100, f"Pattern: {pattern}",
                 fontsize=10, color='orange')

    # Сохранение
    os.makedirs("charts", exist_ok=True)
    filename = f"charts/signal_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()

    return filename
