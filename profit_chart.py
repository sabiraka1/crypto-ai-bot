import pandas as pd
import matplotlib.pyplot as plt
import os

CLOSED_FILE = "closed_trades.csv"
CHART_PATH = "charts/profit_chart.png"

def generate_profit_chart():
    if not os.path.exists(CLOSED_FILE):
        return None, 0.0

    df = pd.read_csv(CLOSED_FILE)
    if len(df) < 2:
        return None, 0.0

    df["pnl_percent"] = df["pnl_percent"] / 100
    df["cumulative_return"] = (1 + df["pnl_percent"]).cumprod()
    df["close_datetime"] = pd.to_datetime(df["close_datetime"])

    plt.figure(figsize=(10, 5))
    plt.plot(df["close_datetime"], df["cumulative_return"], marker='o')
    plt.xticks(rotation=45)
    plt.grid(True)
    plt.title("📈 Кумулятивная доходность")
    plt.xlabel("Дата")
    plt.ylabel("Доход (x)")
    plt.tight_layout()

    os.makedirs("charts", exist_ok=True)
    plt.savefig(CHART_PATH)
    plt.close()

    final_return = df["cumulative_return"].iloc[-1] - 1
    return CHART_PATH, final_return
