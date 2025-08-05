def evaluate_signal(result):
    signal = result.get("signal")
    rsi = result.get("rsi")
    macd = result.get("macd")
    pattern = result.get("pattern", None)

    score = 0.0

    # --- RSI scoring ---
    if signal == "BUY" and rsi < 30:
        score += 0.3
    elif signal == "SELL" and rsi > 70:
        score += 0.3
    elif 45 <= rsi <= 55:
        score += 0.1  # зона неопределённости

    # --- MACD scoring ---
    if signal == "BUY" and macd > 0:
        score += 0.3
    elif signal == "SELL" and macd < 0:
        score += 0.3

    # --- Candle pattern scoring (если есть) ---
    if pattern:
        strong_bullish = ["hammer", "engulfing_bullish"]
        strong_bearish = ["shooting_star", "engulfing_bearish"]

        if signal == "BUY" and pattern in strong_bullish:
            score += 0.3
        elif signal == "SELL" and pattern in strong_bearish:
            score += 0.3

    # --- Уверенность ---
    if score >= 0.8:
        print(f"🔍 Сильный сигнал {signal} с оценкой {score:.2f}")
    else:
        print(f"ℹ️ Слабый/нейтральный сигнал {signal} с оценкой {score:.2f}")

    return score
