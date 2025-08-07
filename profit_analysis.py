import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime, timedelta

CLOSED_FILE = "closed_trades.csv"
CHART_PATH = "charts/profit_analysis.png"

def generate_profit_chart():
    """Создание графика анализа прибыли (legacy функция для совместимости)"""
    return advanced_profit_analysis()

def advanced_profit_analysis():
    """Продвинутый анализ торговой производительности"""
    if not os.path.exists(CLOSED_FILE):
        return None, 0.0

    try:
        df = pd.read_csv(CLOSED_FILE)

        if len(df) < 2:
            return None, 0.0

        # Подготовка данных
        df["close_datetime"] = pd.to_datetime(df["close_datetime"])
        df = df.sort_values("close_datetime")
        
        # Нормализация процентов
        if df["pnl_percent"].abs().max() > 5:
            df["pnl_percent"] = df["pnl_percent"] / 100

        df["cumulative_return"] = (1 + df["pnl_percent"]).cumprod()

        # Создание анализа
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('📊 Продвинутый анализ торговой производительности', fontsize=14, fontweight='bold')

        # 1. Кумулятивная доходность с drawdown
        cumulative_pct = (df["cumulative_return"] - 1) * 100
        running_max = cumulative_pct.cummax()
        drawdown = running_max - cumulative_pct

        ax1.plot(df["close_datetime"], cumulative_pct, label='Доходность', linewidth=2, color='green')
        ax1.fill_between(df["close_datetime"], cumulative_pct, 0, alpha=0.3, color='green')
        ax1_twin = ax1.twinx()
        ax1_twin.fill_between(df["close_datetime"], -drawdown, 0, alpha=0.3, color='red', label='Drawdown')
        
        ax1.set_title('📈 Доходность и просадки')
        ax1.set_ylabel('Доходность (%)', color='green')
        ax1_twin.set_ylabel('Просадка (%)', color='red')
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper left')
        ax1_twin.legend(loc='upper right')

        # 2. Распределение P&L
        ax2.hist(df["pnl_percent"] * 100, bins=min(20, len(df)//2), alpha=0.7, color='blue', edgecolor='black')
        ax2.axvline(x=0, color='red', linestyle='--', alpha=0.7)
        ax2.set_title('📊 Распределение P&L')
        ax2.set_xlabel('P&L (%)')
        ax2.set_ylabel('Количество сделок')
        ax2.grid(True, alpha=0.3)

        # Добавляем статистику на график
        mean_pnl = df["pnl_percent"].mean() * 100
        std_pnl = df["pnl_percent"].std() * 100
        ax2.text(0.7, 0.9, f'Среднее: {mean_pnl:.2f}%\nСтд. откл.: {std_pnl:.2f}%', 
                transform=ax2.transAxes, bbox=dict(boxstyle="round", facecolor='wheat'))

        # 3. Производительность по времени (если есть достаточно данных)
        if len(df) > 10:
            df['month'] = df['close_datetime'].dt.to_period('M')
            monthly_returns = df.groupby('month')['pnl_percent'].sum() * 100
            
            ax3.bar(range(len(monthly_returns)), monthly_returns, 
                   color=['green' if x > 0 else 'red' for x in monthly_returns], alpha=0.7)
            ax3.set_title('📅 Месячная доходность')
            ax3.set_ylabel('Доходность (%)')
            ax3.set_xlabel('Месяц')
            ax3.grid(True, alpha=0.3)
            ax3.set_xticks(range(len(monthly_returns)))
            ax3.set_xticklabels([str(m) for m in monthly_returns.index], rotation=45)
        else:
            # Если мало данных, показываем trend line
            x = np.arange(len(df))
            z = np.polyfit(x, cumulative_pct, 1)
            p = np.poly1d(z)
            
            ax3.scatter(df["close_datetime"], cumulative_pct, alpha=0.6)
            ax3.plot(df["close_datetime"], p(x), "r--", alpha=0.8, label=f'Тренд: {z[0]:.2f}%/сделка')
            ax3.set_title('📈 Тренд доходности')
            ax3.set_ylabel('Кумулятивная доходность (%)')
            ax3.legend()
            ax3.grid(True, alpha=0.3)

        # 4. Детальная статистика
        ax4.axis('off')
        
        # Расчет метрик
        total_trades = len(df)
        winning_trades = len(df[df["pnl_percent"] > 0])
        losing_trades = total_trades - winning_trades
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        avg_win = df[df["pnl_percent"] > 0]["pnl_percent"].mean() * 100 if winning_trades > 0 else 0
        avg_loss = df[df["pnl_percent"] < 0]["pnl_percent"].mean() * 100 if losing_trades > 0 else 0
        
        profit_factor = abs(avg_win * winning_trades / (avg_loss * losing_trades)) if losing_trades > 0 and avg_loss != 0 else float('inf')
        
        total_return = (df["cumulative_return"].iloc[-1] - 1) * 100
        max_drawdown = drawdown.max()
        
        # Sharpe Ratio (упрощенный)
        returns = df["pnl_percent"] * 100
        sharpe_ratio = returns.mean() / returns.std() if returns.std() > 0 else 0
        
        # Calmar Ratio
        calmar_ratio = total_return / max_drawdown if max_drawdown > 0 else float('inf')
        
        stats_text = f"""
📊 ДЕТАЛЬНАЯ СТАТИСТИКА

🎯 Основные метрики:
• Всего сделок: {total_trades}
• Win Rate: {win_rate:.1f}%
• Общая доходность: {total_return:.2f}%
• Макс. просадка: {max_drawdown:.2f}%

💰 Риск/Доходность:
• Profit Factor: {profit_factor:.2f}
• Sharpe Ratio: {sharpe_ratio:.2f}
• Calmar Ratio: {calmar_ratio:.2f}

📈 Сделки:
• Средняя прибыль: {avg_win:.2f}%
• Средний убыток: {avg_loss:.2f}%
• Лучшая: {(df["pnl_percent"].max()*100):.2f}%
• Худшая: {(df["pnl_percent"].min()*100):.2f}%

📅 Временные рамки:
• Период: {(df["close_datetime"].max() - df["close_datetime"].min()).days} дней
• Сделок в день: {total_trades / max(1, (df["close_datetime"].max() - df["close_datetime"].min()).days):.1f}

🏆 Рейтинг: {get_performance_rating(win_rate, profit_factor, sharpe_ratio)}
"""
        
        ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes, fontsize=9,
                verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightcyan', alpha=0.8))

        plt.tight_layout()

        # Сохранение
        os.makedirs("charts", exist_ok=True)
        plt.savefig(CHART_PATH, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()

        final_return = df["cumulative_return"].iloc[-1] - 1
        print(f"✅ Анализ прибыли сохранен: {CHART_PATH}")
        return CHART_PATH, final_return

    except Exception as e:
        print(f"❌ Ошибка анализа прибыли: {e}")
        return None, 0.0

def get_performance_rating(win_rate, profit_factor, sharpe_ratio):
    """Оценка производительности торговой системы"""
    score = 0
    
    # Win Rate (макс 30 баллов)
    if win_rate >= 70:
        score += 30
    elif win_rate >= 60:
        score += 25
    elif win_rate >= 50:
        score += 20
    elif win_rate >= 40:
        score += 10
    
    # Profit Factor (макс 40 баллов)
    if profit_factor >= 2.0:
        score += 40
    elif profit_factor >= 1.5:
        score += 30
    elif profit_factor >= 1.2:
        score += 20
    elif profit_factor >= 1.0:
        score += 10
    
    # Sharpe Ratio (макс 30 баллов)
    if sharpe_ratio >= 2.0:
        score += 30
    elif sharpe_ratio >= 1.5:
        score += 25
    elif sharpe_ratio >= 1.0:
        score += 20
    elif sharpe_ratio >= 0.5:
        score += 10
    
    # Определяем рейтинг
    if score >= 85:
        return "🏆 Отличный (A+)"
    elif score >= 70:
        return "🥇 Хороший (A)"
    elif score >= 55:
        return "🥈 Средний (B)"
    elif score >= 40:
        return "🥉 Удовлетворительный (C)"
    else:
        return "❌ Требует улучшения (D)"

def calculate_risk_metrics(df):
    """Расчет дополнительных метрик риска"""
    returns = df["pnl_percent"]
    
    # Value at Risk (95%)
    var_95 = np.percentile(returns * 100, 5)
    
    # Conditional Value at Risk
    cvar_95 = returns[returns <= np.percentile(returns, 5)].mean() * 100
    
    # Maximum consecutive losses
    consecutive_losses = 0
    max_consecutive_losses = 0
    
    for ret in returns:
        if ret < 0:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0
    
    return {
        "var_95": var_95,
        "cvar_95": cvar_95,
        "max_consecutive_losses": max_consecutive_losses
    }
