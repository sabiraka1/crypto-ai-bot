import joblib
import os
import numpy as np
import logging

# === Логирование ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Путь к модели ===
MODEL_PATH = "models/ai_model.pkl"
model = None

# === Загрузка модели ===
try:
    if os.path.exists(MODEL_PATH):
        model = joblib.load(MODEL_PATH)
        logger.info("✅ AI-модель успешно загружена.")
    else:
        logger.warning("⚠️ AI-модель не найдена. Сигналы будут оцениваться вручную.")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки модели: {e}")

# === Кодировка сигналов ===
def encode_signal(signal):
    return {'BUY': 1, 'SELL': -1, 'HOLD': 0}.get(signal, 0)

# === Оценка сигнала с AI или fallback ===
def evaluate_signal(result):
    signal = result.get("signal")
    rsi = result.get("rsi")
    macd = result.get("macd")
    patterns = result.get("patterns", [])

    logger.info(f"🧪 Оценка сигнала: {signal}, RSI: {rsi}, MACD: {macd}, Patterns: {patterns}")

    if model and signal is not None and rsi is not None and macd is not None:
        try:
            signal_encoded = encode_signal(signal)
            input_data = np.array([[rsi, macd, signal_encoded]])
            logger.info(f"📊 Входные данные модели: {input_data}")

            prediction = model.predict_proba(input_data)[0][1]
            score = round(float(prediction), 2)

            if score >= 0.6:
                logger.info(f"🤖 AI: Уверенный сигнал {signal} с оценкой {score}")
            else:
                logger.info(f"🤖 AI: Нейтральный сигнал {signal} с оценкой {score}")

            return score
        except Exception as e:
            logger.error(f"❌ Ошибка в AI-модели: {e}")

    logger.warning("⚠️ Используется fallback логика для оценки сигнала.")
    return fallback_score(result)

# === Fallback логика ===
def fallback_score(result):
    signal = result.get("signal")
    rsi = result.get("rsi")
    macd = result.get("macd")
    patterns = result.get("patterns", [])
    ema_signal = result.get("ema_signal")
    bollinger = result.get("bollinger")
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

    # ADX тренд
    if adx and adx > 20:
        score += 0.1

    # Stochastic RSI
    if signal == "BUY" and stochrsi < 20:
        score += 0.1
    elif signal == "SELL" and stochrsi > 80:
        score += 0.1

    # Свечные паттерны
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
