import pandas as pd
import os

CSV_FILE = "sinyal_fiyat_analizi.csv"

def analyze_bad_signals(limit=5):
    if not os.path.exists(CSV_FILE):
        return None, None

    try:
        df = pd.read_csv(CSV_FILE, on_bad_lines='skip')
    except Exception as e:
        return None, None

    if len(df) < 10:
        return None, None

    required_cols = {"success", "rsi", "macd", "adx", "stochrsi", "signal"}
    if not required_cols.issubset(df.columns):
        return None, None

    bad_signals = df[df["success"] == 0].copy()
    if bad_signals.empty:
        return None, None

    summary = {
        "❌ Ошибок сигналов": len(bad_signals),
        "📉 Ср. RSI": round(bad_signals["rsi"].mean(), 2),
        "📉 Ср. MACD": round(bad_signals["macd"].mean(), 4),
        "📊 Ср. ADX": round(bad_signals["adx"].mean(), 2),
        "💹 Ср. StochRSI": round(bad_signals["stochrsi"].mean(), 2),
        "⚖️ BUY ошибок": len(bad_signals[bad_signals["signal"] == "BUY"]),
        "⚖️ SELL ошибок": len(bad_signals[bad_signals["signal"] == "SELL"])
    }

    explanations = []
    for _, row in bad_signals.tail(limit).iterrows():
        reason = explain_signal(row)
        explanations.append(reason)

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
    pattern = row.get("pattern", "")

    comments = []

    if signal == "BUY":
        if rsi > 65: comments.append("RSI был высоким")
        if macd < 0: comments.append("MACD был отрицательным")
        if ema != "bullish": comments.append("EMA crossover не подтверждён")
        if boll != "low": comments.append("Цена не у нижней границы Bollinger")
        if adx < 20: comments.append("ADX слабый")
        if stoch > 80: comments.append("StochRSI перекуплен")
        if score < 0.6: comments.append("AI оценка низкая")
        if not comments: comments.append("Рынок пошёл против сигнала")
        return f"❌ BUY @ {price:.2f} — {'; '.join(comments)}"

    elif signal == "SELL":
        if rsi < 35: comments.append("RSI был слишком низким")
        if macd > 0: comments.append("MACD был положительным")
        if ema != "bearish": comments.append("EMA crossover не подтверждён")
        if boll != "high": comments.append("Цена не у верхней границы Bollinger")
        if adx < 20: comments.append("ADX слабый")
        if stoch < 20: comments.append("StochRSI перепродан")
        if score < 0.6: comments.append("AI оценка низкая")
        if not comments: comments.append("Рынок пошёл против сигнала")
        return f"❌ SELL @ {price:.2f} — {'; '.join(comments)}"

    return f"❌ Неудачный сигнал @ {price:.2f}"
