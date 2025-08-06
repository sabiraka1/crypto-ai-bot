def fallback_score(result):
    signal = result.get("signal")
    rsi = result.get("rsi")
    macd = result.get("macd")
    patterns = result.get("patterns", [])
    ema_signal = result.get("ema_signal")  # bullish / bearish / neutral
    bollinger = result.get("bollinger")    # low / high / middle
    adx = result.get("adx")
    stochrsi = result.get("stochrsi")
    score = 0.0

    # RSI
    if signal == "BUY" and rsi < 30:
        score += 0.2
    elif signal == "SELL" and rsi > 70:
        score += 0.2

    # MACD
    if signal == "BUY" and macd > 0:
        score += 0.2
    elif signal == "SELL" and macd < 0:
        score += 0.2

    # EMA crossover
    if signal == "BUY" and ema_signal == "bullish":
        score += 0.15
    elif signal == "SELL" and ema_signal == "bearish":
        score += 0.15

    # Bollinger Bands
    if signal == "BUY" and bollinger == "low":
        score += 0.1
    elif signal == "SELL" and bollinger == "high":
        score += 0.1

    # ADX (только если тренд есть)
    if adx and adx > 20:
        score += 0.1

    # Stochastic RSI
    if signal == "BUY" and stochrsi < 20:
        score += 0.1
    elif signal == "SELL" and stochrsi > 80:
        score += 0.1

    # Candlestick Patterns
    strong_bullish = ["hammer", "engulfing_bullish"]
    strong_bearish = ["shooting_star", "engulfing_bearish"]

    if signal == "BUY" and any(p in strong_bullish for p in patterns):
        score += 0.1
    elif signal == "SELL" and any(p in strong_bearish for p in patterns):
        score += 0.1

    score = round(score, 2)

    if score >= 0.6:
        logger.info(f"🔍 Ручной анализ: Уверенный сигнал {signal} с оценкой {score}")
    else:
        logger.info(f"ℹ️ Ручной анализ: Нейтральный сигнал {signal} с оценкой {score}")

    return score
