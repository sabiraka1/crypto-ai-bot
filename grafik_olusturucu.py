import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
import pandas as pd
import ccxt

exchange = ccxt.gateio()
CHART_DIR = "charts"

def fetch_ohlcv():
    """Получение OHLCV данных"""
    try:
        bars = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Ошибка получения данных: {e}")
        return None

def cleanup_old_charts():
    """Очистка старых графиков"""
    if not os.path.exists(CHART_DIR):
        return
        
    now = datetime.now()
    for filename in os.listdir(CHART_DIR):
        file_path = os.path.join(CHART_DIR, filename)
        if filename.endswith(".png"):
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                if now - file_mtime > timedelta(hours=12):  # Удаляем файлы старше 12 часов
                    os.remove(file_path)
            except Exception as e:
                print(f"❌ Ошибка удаления {filename}: {e}")

def draw_rsi_macd_chart(result):
    """Создание расширенного графика с техническим анализом"""
    cleanup_old_charts()
    
    df = fetch_ohlcv()
    if df is None:
        return None
    
    # Рассчитываем индикаторы
    df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
    macd_indicator = MACD(close=df['close'])
    df['macd'] = macd_indicator.macd()
    df['macd_signal'] = macd_indicator.macd_signal()
    df['macd_histogram'] = macd_indicator.macd_diff()
    
    # Bollinger Bands
    bb = BollingerBands(close=df['close'])
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    df['bb_middle'] = bb.bollinger_mavg()
    
    # Извлекаем данные из результата
    signal = result.get('signal', 'NONE')
    rsi = result.get('rsi', 0)
    macd_val = result.get('macd', 0)
    pattern = result.get('pattern', 'NONE')
    pattern_score = result.get('pattern_score', 0)
    pattern_direction = result.get('pattern_direction', 'NEUTRAL')
    confidence = result.get('confidence', 0)
    price = result.get('price', 0)
    support = result.get('support', 0)
    resistance = result.get('resistance', 0)
    
    # Создание графика
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle(f'📊 Технический анализ BTC/USDT | {signal} | Confidence: {confidence:.1f}%', 
                 fontsize=14, fontweight='bold')
    
    # 1. Цена + Bollinger Bands + Поддержка/Сопротивление
    ax1.plot(df['timestamp'], df['close'], label='Close', color='black', linewidth=2)
    ax1.plot(df['timestamp'], df['bb_upper'], label='BB Upper', color='red', alpha=0.7)
    ax1.plot(df['timestamp'], df['bb_lower'], label='BB Lower', color='green', alpha=0.7)
    ax1.plot(df['timestamp'], df['bb_middle'], label='BB Middle', color='blue', alpha=0.5)
    ax1.fill_between(df['timestamp'], df['bb_upper'], df['bb_lower'], alpha=0.1, color='gray')
    
    # Добавляем уровни поддержки/сопротивления
    if support > 0:
        ax1.axhline(y=support, color='green', linestyle='--', alpha=0.8, label=f'Support: {support:.2f}')
    if resistance > 0:
        ax1.axhline(y=resistance, color='red', linestyle='--', alpha=0.8, label=f'Resistance: {resistance:.2f}')
    
    # Маркер текущего сигнала
    last_row = df.iloc[-1]
    signal_colors = {
        'STRONG_BUY': 'darkgreen', 'BUY': 'green',
        'STRONG_SELL': 'darkred', 'SELL': 'red',
        'HOLD': 'gray', 'ERROR': 'purple'
    }
    signal_color = signal_colors.get(signal, 'black')
    
    ax1.scatter(last_row['timestamp'], last_row['close'], 
               color=signal_color, s=100, zorder=5, label=f'{signal} @ {price:.2f}')
    
    ax1.set_title(f'Price & Bollinger Bands | Pattern: {pattern} ({pattern_score:.1f})')
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)
    
    # 2. RSI
    ax2.plot(df['timestamp'], df['rsi'], label='RSI', color='purple', linewidth=2)
    ax2.axhline(70, color='red', linestyle='--', linewidth=1, alpha=0.8, label='Overbought (70)')
    ax2.axhline(30, color='green', linestyle='--', linewidth=1, alpha=0.8, label='Oversold (30)')
    ax2.axhline(50, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
    ax2.fill_between(df['timestamp'], 70, 100, alpha=0.1, color='red')
    ax2.fill_between(df['timestamp'], 0, 30, alpha=0.1, color='green')
    
    # Текущее значение RSI
    ax2.scatter(last_row['timestamp'], rsi, color=signal_color, s=80, zorder=5)
    ax2.text(last_row['timestamp'], rsi + 5, f'{rsi:.1f}', 
             ha='center', va='bottom', fontweight='bold', color=signal_color)
    
    ax2.set_title(f'RSI (14) | Current: {rsi:.1f}')
    ax2.set_ylim(0, 100)
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.tick_params(axis='x', rotation=45)
    
    # 3. MACD
    ax3.plot(df['timestamp'], df['macd'], label='MACD', color='blue', linewidth=2)
    ax3.plot(df['timestamp'], df['macd_signal'], label='Signal', color='orange', linewidth=2)
    ax3.bar(df['timestamp'], df['macd_histogram'], label='Histogram', 
            color=['green' if x > 0 else 'red' for x in df['macd_histogram']], 
            alpha=0.6, width=pd.Timedelta(minutes=10))
    ax3.axhline(0, color='black', linestyle='-', linewidth=0.5)
    
    # Текущее значение MACD
    ax3.scatter(last_row['timestamp'], macd_val, color=signal_color, s=80, zorder=5)
    
    ax3.set_title(f'MACD | Current: {macd_val:.4f}')
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3)
    ax3.tick_params(axis='x', rotation=45)
    
    # 4. Информационная панель
    ax4.axis('off')  # Убираем оси
    
    # Создаем информационную таблицу
    info_text = f"""
📊 SIGNAL ANALYSIS

🎯 Signal: {signal}
📈 Confidence: {confidence:.1f}%
💰 Price: ${price:.2f}

📊 TECHNICAL INDICATORS
• RSI (14): {rsi:.1f}
• MACD: {macd_val:.4f}
• Pattern: {pattern}
• Pattern Score: {pattern_score:.1f}/10
• Direction: {pattern_direction}

💹 LEVELS
• Support: ${support:.2f}
• Resistance: ${resistance:.2f}

🕯️ PATTERN DETAILS
Score: {pattern_score:.1f}/10
Direction: {pattern_direction}
Strength: {'Strong' if pattern_score >= 6 else 'Moderate' if pattern_score >= 4 else 'Weak'}

⏰ Generated: {datetime.now().strftime('%H:%M:%S')}
"""
    
    ax4.text(0.05, 0.95, info_text, transform=ax4.transAxes, fontsize=10,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8))
    
    # Настройка layout
    plt.tight_layout()
    
    # Сохранение файла
    os.makedirs(CHART_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{CHART_DIR}/signal_chart_{timestamp}.png"
    
    try:
        plt.savefig(filename, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        print(f"✅ График сохранен: {filename}")
        return filename
    except Exception as e:
        print(f"❌ Ошибка сохранения графика: {e}")
        plt.close()
        return None

def draw_simplified_chart(result):
    """Создание упрощенного графика для быстрого анализа"""
    df = fetch_ohlcv()
    if df is None:
        return None
    
    # Базовые индикаторы
    df['rsi'] = RSIIndicator(close=df['close']).rsi()
    macd_indicator = MACD(close=df['close'])
    df['macd'] = macd_indicator.macd()
    
    signal = result.get('signal', 'NONE')
    pattern = result.get('pattern', 'NONE')
    confidence = result.get('confidence', 0)
    
    # Простой график
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle(f'{signal} | {pattern} | Confidence: {confidence:.1f}%', fontsize=12)
    
    # Цена
    ax1.plot(df['timestamp'], df['close'], color='black', linewidth=2)
    ax1.set_title('BTC/USDT Price')
    ax1.grid(True, alpha=0.3)
    
    # RSI
    ax2.plot(df['timestamp'], df['rsi'], color='purple', linewidth=2)
    ax2.axhline(70, color='red', linestyle='--', alpha=0.7)
    ax2.axhline(30, color='green', linestyle='--', alpha=0.7)
    ax2.set_title('RSI (14)')
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Сохранение
    os.makedirs(CHART_DIR, exist_ok=True)
    filename = f"{CHART_DIR}/simple_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    
    try:
        plt.savefig(filename, dpi=200, bbox_inches='tight')
        plt.close()
        return filename
    except Exception as e:
        print(f"Ошибка сохранения упрощенного графика: {e}")
        plt.close()
        return None
