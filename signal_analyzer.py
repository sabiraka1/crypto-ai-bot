# signal_analyzer.py

import pandas as pd
import os

CSV_FILE = "sinyal_fiyat_analizi.csv"

def analyze_bad_signals(limit=5):
    if not os.path.exists(CSV_FILE):
        print("⚠️ CSV-файл не найден.")
        return None, None

    df = pd.read_csv(CSV_FILE)
    if len(df) < 10:
        print("⚠️ Недостаточно данных для анализа.")
        return None, None

    bad_signals = df[df["success"] == 0].copy()
    if bad_signals.empty:
        return None, None

    # === Общая сводка ===
    avg_rsi = bad_signals["rsi"].mean()
    avg_macd = bad_signals["macd"].mean()
    count_buy = len(bad_signals[bad_signals["signal"] == "BUY"])
    count_sell = len(bad_signals[bad_signals["signal"] == "SELL"])

    summary = {
        "Всего неудачных сигналов": len(bad_signals),
        "Средний RSI": round(avg_rsi, 2),
        "Средний MACD": round(avg_macd, 4),
        "Ошибок BUY": count_buy,
        "Ошибок SELL": count_sell
    }

    # === Интерпретации сигналов (вручную) ===
    explanations = []
    for _, row in bad_signals.tail(limit).iterrows():
        reason = explain_signal(row)
        explanations.append(reason)

    return summary, explanations


def explain_signal(row):
    signal = row["signal"]
    rsi = row["rsi"]
    macd = row["macd"]
    score = row.get("score", 0.0)
    price = row.get("price", 0.0)

    comments = []

    if signal == "BUY":
        if rsi > 65:
            comments.append("RSI был слишком высоким")
        if macd < 0:
            comments.append("MACD был отрицательным")
        if score < 0.6:
            comments.append("AI дал слабую оценку")
        if not comments:
            comments.append("рынок пошёл против сигнала")
        return f"❌ BUY @ {price:.2f} — {'; '.join(comments)}"

    elif signal == "SELL":
        if rsi < 35:
            comments.append("RSI был слишком низким")
        if macd > 0:
            comments.append("MACD был положительным")
        if score < 0.6:
            comments.append("AI дал слабую оценку")
        if not comments:
            comments.append("рынок пошёл против сигнала")
        return f"❌ SELL @ {price:.2f} — {'; '.join(comments)}"

    return f"❌ Неудачный сигнал @ {price:.2f}"
