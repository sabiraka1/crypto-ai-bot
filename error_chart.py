# error_chart.py

import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter

def plot_error_reasons():
    df = pd.read_csv("error_signals.csv")
    if df.empty:
        print("⚠️ Нет данных для графика.")
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
    plt.title("📊 Частота причин ошибок")
    plt.xlabel("Количество")
    plt.tight_layout()
    plt.savefig("charts/error_reasons_chart.png")
    plt.close()
    print("✅ График ошибок сохранён: charts/error_reasons_chart.png")
