import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter
import os

def plot_error_reasons():
    if not os.path.exists("error_signals.csv"):
        print("❌ Нет файла error_signals.csv")
        return

    df = pd.read_csv("error_signals.csv")
    if df.empty:
        print("⚠️ Нет данных для анализа.")
        return

    reasons = df["explanation"].dropna().tolist()
    all_causes = []
    for r in reasons:
        parts = r.split(" — ")[-1].split("; ")
        all_causes.extend(parts)

    counter = Counter(all_causes)
    labels, values = zip(*counter.items())

    plt.figure(figsize=(10, 5))
    plt.barh(labels, values)
    plt.title("📊 Причины ошибок")
    plt.xlabel("Количество")
    plt.tight_layout()

    os.makedirs("charts", exist_ok=True)
    plt.savefig("charts/error_reasons_chart.png")
    plt.close()
    print("✅ График ошибок сохранён: charts/error_reasons_chart.png")
