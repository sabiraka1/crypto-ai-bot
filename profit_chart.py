import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
from datetime import datetime, timedelta
import numpy as np

CLOSED_FILE = "closed_trades.csv"
CHART_PATH = "charts/profit_chart.png"

def generate_profit_chart():
    """Создание детального графика прибыли"""
    if not os.path.exists(CLOSED_FILE):
        return None, 0.0

    try:
        df = pd.read_csv(CLOSED_FILE)
        
        if len(df) < 2:
            return None, 0.0

        # Подготовка данных
        df["close_datetime"] = pd.to_datetime(df["close_datetime"])
        df = df.sort_values("close_datetime")
        
        # Преобразуем проценты в доли если нужно
        if df["pnl_percent"].abs().max() > 5:  # Если значения больше 5, значит в процентах
            df["pnl_percent"] = df["pnl_percent"] / 100
        
        # Расчет кумулятивной доходности
        df["cumulative_return"] = (1 + df["pnl_percent"]).cumprod()
        df["cumulative_percent"] = (df["cumulative_return"] - 1) * 100
        
        # Создание расширенного графика
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('📈 Анализ торговой производительности', fontsize=16, fontweight='bold')
        
        # 1. Кумулятивная доходность
        ax1.plot(df["close_datetime"], df["cumulative_percent"], 
                marker='o', linewidth=2, markersize=4, color='green')
        ax1.fill_between(df["close_datetime"], df["cumulative_percent"], 0, alpha=0.3, color='green')
        ax1.axhline(y=0, color='black', linestyle='-', alpha=0.5)
        ax1.set_title("📈 Кумулятивная доходность (%)", fontweight='bold')
        ax1.set_ylabel("Доходность (%)")
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax1.tick_params(axis='x', rotation=45)
        
        # Добавляем аннотации к важным точкам
        max_profit_idx = df["cumulative_percent"].idxmax()
        min_profit_idx = df["cumulative_percent"].idxmin()
        
        ax1.annotate(f'📈 Пик: {df.loc[max_profit_idx, "cumulative_percent"]:.1f}%',
                    xy=(df.loc[max_profit_idx, "close_datetime"], df.loc[max_profit_idx, "cumulative_percent"]),
                    xytext=(10, 10), textcoords='offset points',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='green', alpha=0.7),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
        
        ax1.annotate(f'📉 Минимум: {df.loc[min_profit_idx, "cumulative_percent"]:.1f}%',
                    xy=(df.loc[min_profit_idx, "close_datetime"], df.loc[min_profit_idx, "cumulative_percent"]),
                    xytext=(10, -20), textcoords='offset points',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='red', alpha=0.7),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
        
        # 2. Распределение P&L по сделкам
        colors = ['green' if x > 0 else 'red' for x in df["pnl_percent"]]
        bars = ax2.bar(range(len(df)), df["pnl_percent"] * 100, color=colors, alpha=0.7)
        ax2.axhline(y=0, color='black', linestyle='-', alpha=0.5)
        ax2.set_title("💰 P&L по сделкам (%)", fontweight='bold')
        ax2.set_xlabel("Номер сделки")
        ax2.set_ylabel("P&L (%)")
        ax2.grid(True, alpha=0.3)
        
        # Добавляем значения на барах
        for i, bar in enumerate(bars):
            height = bar.get_height()
            if abs(height) > 0.5:  # Показываем только значимые значения
                ax2.text(bar.get_x() + bar.get_width()/2., height + (0.1 if height > 0 else -0.3),
                        f'{height:.1f}%', ha='center', va='bottom' if height > 0 else 'top',
                        fontsize=8)
        
        # 3. Статистика по типам сигналов
        if 'signal' in df.columns:
            signal_stats = df.groupby('signal')['pnl_percent'].agg(['count', 'mean', 'sum'])
            signal_stats['mean_percent'] = signal_stats['mean'] * 100
            signal_stats['total_percent'] = signal_stats['sum'] * 100
            
            ax3.bar(signal_stats.index, signal_stats['mean_percent'], 
                   color=['green' if x > 0 else 'red' for x in signal_stats['mean_percent']], alpha=0.7)
            ax3.set_title("📊 Средняя доходность по типам сигналов", fontweight='bold')
            ax3.set_ylabel("Средний P&L (%)")
            ax3.grid(True, alpha=0.3)
            ax3.tick_params(axis='x', rotation=45)
            
            # Добавляем количество сделок на бары
            for i, (signal, row) in enumerate(signal_stats.iterrows()):
                ax3.text(i, row['mean_percent'] + (0.1 if row['mean_percent'] > 0 else -0.3),
                        f"n={int(row['count'])}", ha='center', va='bottom' if row['mean_percent'] > 0 else 'top')
        
        # 4. Информационная панель
        ax4.axis('off')
        
        # Расчет статистики
        total_trades = len(df)
        winning_trades = len(df[df["pnl_percent"] > 0])
        losing_trades = len(df[df["pnl_percent"] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        avg_win = df[df["pnl_percent"] > 0]["pnl_percent"].mean() * 100 if winning_trades > 0 else 0
        avg_loss = df[df["pnl_percent"] < 0]["pnl_percent"].mean() * 100 if losing_trades > 0 else 0
        
        profit_factor = abs(avg_win * winning_trades / (avg_loss * losing_trades)) if losing_trades > 0 and avg_loss != 0 else float('inf')
        
        total_return = df["cumulative_percent"].iloc[-1]
        max_drawdown = (df["cumulative_percent"].cummax() - df["cumulative_percent"]).max()
        
        # Создание текста статистики
        stats_text = f"""
📊 ТОРГОВАЯ СТАТИСТИКА

📈 Общие показатели:
• Всего сделок: {total_trades}
• Прибыльных: {winning_trades} ({win_rate:.1f}%)
• Убыточных: {losing_trades} ({100-win_rate:.1f}%)

💰 Доходность:
• Общая доходность: {total_return:.2f}%
• Средняя прибыль: {avg_win:.2f}%
• Средний убыток: {avg_loss:.2f}%
• Profit Factor: {profit_factor:.2f}

📉 Риски:
• Макс. просадка: {max_drawdown:.2f}%
• Лучшая сделка: {(df["pnl_percent"].max()*100):.2f}%
• Худшая сделка: {(df["pnl_percent"].min()*100):.2f}%

📅 Период:
• Начало: {df["close_datetime"].min().strftime('%Y-%m-%d')}
• Конец: {df["close_datetime"].max().strftime('%Y-%m-%d')}
• Дней торговли: {(df["close_datetime"].max() - df["close_datetime"].min()).days}

⏰ Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
        
        ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes, fontsize=10,
                verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightblue', alpha=0.8))
        
        # Настройка layout
        plt.tight_layout()
        
        # Сохранение
        os.makedirs("charts", exist_ok=True)
        plt.savefig(CHART_PATH, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        final_return = df["cumulative_return"].iloc[-1] - 1
        print(f"✅ График прибыли сохранен: {CHART_PATH}")
        return CHART_PATH, final_return
        
    except Exception as e:
        print(f"❌ Ошибка создания графика прибыли: {e}")
        return None, 0.0

def generate_simple_profit_chart():
    """Создание простого графика прибыли"""
    if not os.path.exists(CLOSED_FILE):
        return None, 0.0

    try:
        df = pd.read_csv(CLOSED_FILE)
        
        if len(df) < 2:
            return None, 0.0

        df["close_datetime"] = pd.to_datetime(df["close_datetime"])
        df = df.sort_values("close_datetime")
        
        if df["pnl_percent"].abs().max() > 5:
            df["pnl_percent"] = df["pnl_percent"] / 100
        
        df["cumulative_return"] = (1 + df["pnl_percent"]).cumprod()
        
        # Простой график
        plt.figure(figsize=(10, 6))
        plt.plot(df["close_datetime"], (df["cumulative_return"] - 1) * 100, 
                marker='o', linewidth=2, color='green')
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.5)
        plt.title("📈 Кумулятивная доходность")
        plt.xlabel("Дата")
        plt.ylabel("Доходность (%)")
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        simple_path = "charts/simple_profit_chart.png"
        os.makedirs("charts", exist_ok=True)
        plt.savefig(simple_path, dpi=200, bbox_inches='tight')
        plt.close()
        
        final_return = df["cumulative_return"].iloc[-1] - 1
        return simple_path, final_return
        
    except Exception as e:
        print(f"Ошибка простого графика: {e}")
        return None, 0.0

def get_profit_summary():
    """Получение краткой сводки по прибыли"""
    if not os.path.exists(CLOSED_FILE):
        return "📊 Нет данных о закрытых сделках"
    
    try:
        df = pd.read_csv(CLOSED_FILE)
        
        if len(df) == 0:
            return "📊 Нет данных о сделках"
        
        if df["pnl_percent"].abs().max() > 5:
            df["pnl_percent"] = df["pnl_percent"] / 100
        
        total_trades = len(df)
        winning_trades = len(df[df["pnl_percent"] > 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        total_return = ((1 + df["pnl_percent"]).prod() - 1) * 100
        avg_return = df["pnl_percent"].mean() * 100
        
        summary = f"""
📊 Краткая сводка:
• Сделок: {total_trades}
• Win Rate: {win_rate:.1f}%
• Общая прибыль: {total_return:.2f}%
• Средняя сделка: {avg_return:.2f}%
"""
        return summary
        
    except Exception as e:
        return f"❌ Ошибка: {e}"
