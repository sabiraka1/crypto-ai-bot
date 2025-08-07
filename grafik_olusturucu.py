# grafik_olusturucu.py

import os
import matplotlib
matplotlib.use('Agg')  # важно для Replit/Render
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
import pandas as pd
import ccxt

exchange = ccxt.gateio()

CHART_DIR = "charts"

def fetch_ohlcv():
    bars = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=50)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def cleanup_old_charts():
    if not os.path.exists(CHART_DIR):
        return

    now = datetime.now()
    for filename in os.listdir(CHART_DIR):
        file_path = os.path.join(CHART_DIR, filename)
        if filename.endswith(".png"):
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            if now - file_mtime > timedelta(days=1):
                try:
                    os.remove(file_path)
                    print(f"🧹 Удалён старый график: {filename}")
                except Exception as e:
                    print(f"❌ Ошибка при удалении {filename}: {e}")

def draw_chart(result):
    cleanup_old_charts()
    df = fetch_ohlcv()

    # Расчёт индикаторов
    rsi_indicator = RSIIndicator(close=df['close'], window=14)
    df['rsi'] = rsi_indicator.rsi()

    macd = MACD(close=df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    last_row = df.iloc[-1]
    signal = result.get('signal', 'NONE')
    rsi = result.get('rsi', 0)
    macd_val = result.get('macd', 0)
    patterns = result.get('patterns', [])

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)

    # 📈 Цена
    ax1.plot(df['timestamp'], df['close'], label='Close', color='black')
    ax1.set_title(f"📊 Сигнал: {signal} | Паттерны: {', '.join(patterns) if patterns else 'нет'}")
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

    # 🎯 Аннотация сигнала
    color = 'green' if signal == 'BUY' else 'red' if signal == 'SELL' else 'gray'
    ax1.annotate(f"Signal: {signal}", xy=(last_row['timestamp'], last_row['close']),
                 xytext=(last_row['timestamp'], last_row['close'] + 100),
                 arrowprops=dict(facecolor=color, shrink=0.05),
                 fontsize=10, color=color)

    # 📍 Паттерны
    if patterns:
        ax1.text(last_row['timestamp'], last_row['close'] - 100,
                 f"Patterns: {', '.join(patterns)}", fontsize=10, color='orange')

    os.makedirs(CHART_DIR, exist_ok=True)
    filename = f"{CHART_DIR}/signal_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()

    return filename
