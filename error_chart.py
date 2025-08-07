import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter
import os

ERROR_FILE = "error_signals.csv"
CHART_DIR = "charts"

def plot_error_reasons():
    """Создание графика причин ошибок"""
    if not os.path.exists(ERROR_FILE):
        print("❌ Нет файла error_signals.csv")
        return None

    try:
        df = pd.read_csv(ERROR_FILE)
        if df.empty:
            print("⚠️ Нет данных для анализа ошибок.")
            return None

        # Анализ объяснений ошибок
        if "explanation" not in df.columns:
            print("⚠️ Нет колонки explanation")
            return None

        reasons = df["explanation"].dropna().tolist()
        if not reasons:
            print("⚠️ Нет данных об объяснениях ошибок")
            return None

        # Разбираем причины
        all_causes = []
        for reason in reasons:
            if " — " in reason:
                causes = reason.split(" — ")[-1].split("; ")
                all_causes.extend(causes)
            else:
                all_causes.append(reason)

        # Подсчитываем частоту
        counter = Counter(all_causes)
        
        if not counter:
            print("⚠️ Не удалось извлечь причины ошибок")
            return None

        # Создаем график
        labels, values = zip(*counter.most_common(10))  # Топ 10 причин
        
        plt.figure(figsize=(12, 8))
        colors = plt.cm.Reds(np.linspace(0.4, 0.8, len(labels)))
        bars = plt.barh(labels, values, color=colors)
        
        plt.title("📊 Топ-10 причин неудачных сигналов", fontsize=14, fontweight='bold')
        plt.xlabel("Количество случаев")
        plt.ylabel("Причины ошибок")
        
        # Добавляем значения на бары
        for bar in bars:
            width = bar.get_width()
            plt.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                    f'{int(width)}', ha='left', va='center')
        
        plt.tight_layout()
        
        # Сохранение
        os.makedirs(CHART_DIR, exist_ok=True)
        chart_path = f"{CHART_DIR}/error_reasons_chart.png"
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✅ График причин ошибок сохранён: {chart_path}")
        return chart_path
        
    except Exception as e:
        print(f"❌ Ошибка создания графика ошибок: {e}")
        return None

def plot_error_distribution():
    """График распределения ошибок по различным параметрам"""
    if not os.path.exists(ERROR_FILE):
        return None
        
    try:
        df = pd.read_csv(ERROR_FILE)
        if len(df) < 5:
            return None
            
        # Создаем subplot
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
        fig.suptitle('📊 Анализ распределения ошибок', fontsize=16, fontweight='bold')
        
        # 1. Распределение по типам сигналов
        if 'signal' in df.columns:
            signal_counts = df['signal'].value_counts()
            ax1.pie(signal_counts.values, labels=signal_counts.index, autopct='%1.1f%%', startangle=90)
            ax1.set_title('Ошибки по типам сигналов')
        else:
            ax1.text(0.5, 0.5, 'Нет данных\nо сигналах', ha='center', va='center', transform=ax1.transAxes)
            ax1.set_title('Типы сигналов')
        
        # 2. Распределение убытков
        if 'pnl_percent' in df.columns:
            losses = df['pnl_percent'] * 100  # Конвертируем в проценты
            ax2.hist(losses, bins=min(15, len(df)//2), alpha=0.7, color='red', edgecolor='black')
            ax2.set_title('Распределение убытков (%)')
            ax2.set_xlabel('Убыток (%)')
            ax2.set_ylabel('Количество')
            ax2.axvline(losses.mean(), color='blue', linestyle='--', 
                       label=f'Средний: {losses.mean():.1f}%')
            ax2.legend()
        else:
            ax2.text(0.5, 0.5, 'Нет данных\nо P&L', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('Убытки')
        
        # 3. RSI при ошибках
        if 'rsi' in df.columns:
            ax3.scatter(range(len(df)), df['rsi'], alpha=0.6, color='purple')
            ax3.axhline(y=70, color='red', linestyle='--', alpha=0.7, label='Перекуплен')
            ax3.axhline(y=30, color='green', linestyle='--', alpha=0.7, label='Перепродан')
            ax3.set_title('RSI при неудачных сигналах')
            ax3.set_ylabel('RSI')
            ax3.set_xlabel('Номер ошибки')
            ax3.legend()
            ax3.grid(True, alpha=0.3)
        else:
            ax3.text(0.5, 0.5, 'Нет данных\nо RSI', ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('RSI')
        
        # 4. AI Score при ошибках
        if 'score' in df.columns:
            scores = df['score']
            ax4.hist(scores, bins=min(10, len(df)//2), alpha=0.7, color='orange', edgecolor='black')
            ax4.axvline(scores.mean(), color='blue', linestyle='--', 
                       label=f'Средний: {scores.mean():.3f}')
            ax4.axvline(0.65, color='red', linestyle='--', alpha=0.7, label='Порог: 0.65')
            ax4.set_title('AI Score при ошибках')
            ax4.set_xlabel('AI Score')
            ax4.set_ylabel('Количество')
            ax4.legend()
        else:
            ax4.text(0.5, 0.5, 'Нет данных\nо AI Score', ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('AI Score')
        
        plt.tight_layout()
        
        # Сохранение
        os.makedirs(CHART_DIR, exist_ok=True)
        chart_path = f"{CHART_DIR}/error_distribution.png"
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✅ График распределения ошибок сохранён: {chart_path}")
        return chart_path
        
    except Exception as e:
        print(f"❌ Ошибка создания графика распределения: {e}")
        return None

def plot_error_timeline():
    """График ошибок по времени"""
    if not os.path.exists(ERROR_FILE):
        return None
        
    try:
        df = pd.read_csv(ERROR_FILE)
        if len(df) < 3:
            return None
            
        # Конвертируем timestamp
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        # Группируем по дням
        df['date'] = df['timestamp'].dt.date
        daily_errors = df.groupby('date').size()
        
        plt.figure(figsize=(12, 6))
        plt.plot(daily_errors.index, daily_errors.values, marker='o', linewidth=2, markersize=6)
        plt.title('📅 Количество ошибок по дням', fontsize=14, fontweight='bold')
        plt.xlabel('Дата')
        plt.ylabel('Количество ошибок')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        
        # Добавляем тренд
        if len(daily_errors) > 2:
            x = np.arange(len(daily_errors))
            z = np.polyfit(x, daily_errors.values, 1)
            p = np.poly1d(z)
            plt.plot(daily_errors.index, p(x), "r--", alpha=0.8, 
                    label=f'Тренд: {z[0]:.2f} ошибок/день')
            plt.legend()
        
        plt.tight_layout()
        
        # Сохранение
        os.makedirs(CHART_DIR, exist_ok=True)
        chart_path = f"{CHART_DIR}/error_timeline.png"
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✅ График временной линии ошибок сохранён: {chart_path}")
        return chart_path
        
    except Exception as e:
        print(f"❌ Ошибка создания временного графика: {e}")
        return None

def create_error_report():
    """Создание комплексного отчета по ошибкам"""
    charts = []
    
    # Создаем все графики
    chart1 = plot_error_reasons()
    if chart1:
        charts.append(chart1)
        
    chart2 = plot_error_distribution()
    if chart2:
        charts.append(chart2)
        
    chart3 = plot_error_timeline()
    if chart3:
        charts.append(chart3)
    
    return charts

if __name__ == "__main__":
    print("🔍 Создание анализа ошибок...")
    charts = create_error_report()
    
    if charts:
        print(f"✅ Создано {len(charts)} графиков анализа ошибок")
        for chart in charts:
            print(f"  📊 {chart}")
    else:
        print("❌ Не удалось создать графики анализа ошибок")
