# signal_analyzer.py

import pandas as pd
import os

CSV_FILE = "sinyal_fiyat_analizi.csv"

def analyze_bad_signals(limit=5):
    if not os.path.exists(CSV_FILE):
        print("⚠️ CSV-файл не найден.")
        return None, None

    try:
        df = pd.read_csv(CSV_FILE)
    except Exception as e:
        print(f"❌ Ошибка чтения CSV: {e}")
        return None, None

    if len(df) < 10:
        print("⚠️ Недостаточно данных для анализа.")
        return None, None

    # Проверка нужных колонок
    required_cols = {"success", "rsi", "macd", "adx", "stochrsi", "signal"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        print(f"❌ Отсутствуют колонки: {missing_cols}")
        return None, None

    bad_signals = df[df["success"] == 0].copy()
    if bad_signals.empty:
        return None, None

    summary = {
        "❌ Всего неудачных сигналов": len(bad_signals),
        "📉 Средний RSI": round(bad_signals["rsi"].mean(), 2),
        "📉 Средний MACD": round(bad_signals["macd"].mean(), 4),
        "📊 Средний ADX": round(bad_signals["adx"].mean(), 2),
        "💹 Средний StochRSI": round(bad_signals["stochrsi"].mean(), 2),
        "⚖️ BUY ошибок": len(bad_signals[bad_signals["signal"] == "BUY"]),
        "⚖️ SELL ошибок": len(bad_signals[bad_signals["signal"] == "SELL"])
    }

    explanations = []
    for _, row in bad_signals.tail(limit).iterrows():
        explanations.append(explain_signal(row))

    return summary, explanations

def explain_signal(row):
    signal = row.get("signal", "")
    rsi = row.get("rsi", 0)
    macd = row.get("macd", 0)
    score = row.get("score", 0.0)
    price = row.get("price", 0.0)
    adx = row.get("adx", 0)
    stoch = row.get("stochrsi", 0)
    ema = row.get("ema_signal", "")
    boll = row.get("bollinger", "")

    comments = []

    if signal == "BUY":
        if rsi > 65: comments.append("RSI был высоким")
        if macd < 0: comments.append("MACD был отрицательным")
        if ema != "bullish": comments.append("EMA crossover не подтверждён")
        if boll != "low": comments.append("Цена не у нижней границы Bollinger")
        if adx < 20: comments.append("ADX показал слабый тренд")
        if stoch > 80: comments.append("StochRSI был перекуплен")
        if score < 0.6: comments.append("AI дал слабую оценку")
        if not comments: comments.append("рынок пошёл против сигнала")
        return f"❌ BUY @ {price:.2f} — {'; '.join(comments)}"

    elif signal == "SELL":
        if rsi < 35: comments.append("RSI был слишком низким")
        if macd > 0: comments.append("MACD был положительным")
        if ema != "bearish": comments.append("EMA crossover не подтверждён")
        if boll != "high": comments.append("Цена не у верхней границы Bollinger")
        if adx < 20: comments.append("ADX показал слабый тренд")
        if stoch < 20: comments.append("StochRSI был перепродан")
        if score < 0.6: comments.append("AI дал слабую оценку")
        if not comments: comments.append("рынок пошёл против сигнала")
        return f"❌ SELL @ {price:.2f} — {'; '.join(comments)}"

    return f"❌ Неудачный сигнал @ {price:.2f}"
