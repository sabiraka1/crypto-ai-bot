import pandas as pd
import matplotlib.pyplot as plt
import os

def generate_profit_chart():
    file = "closed_trades.csv"
    if not os.path.exists(file):
        print("❌ Нет данных о закрытых сделках.")
        return None

    df = pd.read_csv(file)
    if df.empty:
        print("❌ Файл пуст.")
        return None

    # Убедимся, что нужные колонки есть
    if 'pnl_percent' not in df.columns:
        print("❌ Нет столбца 'pnl_percent'.")
        return None

    # Кумулятивная доходность
    df['cumulative'] = df['pnl_percent'].cumsum()
    df['close_datetime'] = pd.to_datetime(df['close_datetime'])

    # Построение графика
    plt.figure(figsize=(10, 5))
    plt.plot(df['close_datetime'], df['cumulative'], marker='o', linestyle='-', linewidth=2)
    plt.xlabel("Время закрытия")
    plt.ylabel("Кумулятивная доходность (%)")
    plt.title("📈 Доходность стратегии")
    plt.grid(True)
    plt.tight_layout()
    
    output_file = "profit_chart.png"
    plt.savefig(output_file)
    print(f"✅ График сохранён как {output_file}")
    return output_file
