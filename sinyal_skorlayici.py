import joblib
import os
import numpy as np
import logging

# === Логирование ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_PATH = "models/ai_model.pkl"
model = None

try:
    if os.path.exists(MODEL_PATH):
        model = joblib.load(MODEL_PATH)
        logger.info("✅ AI-модель успешно загружена.")
    else:
        logger.warning("⚠️ AI-модель не найдена. Сигналы будут оцениваться вручную.")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки модели: {e}")

def encode_signal(signal):
    return {'BUY': 1, 'SELL': -1, 'NONE': 0}.get(signal, 0)

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

            if score >= 0.8:
                logger.info(f"🤖 AI: Сильный сигнал {signal} с оценкой {score}")
            else:
                logger.info(f"🤖 AI: Слабый/нейтральный сигнал {signal} с оценкой {score}")

            return score
        except Exception as e:
            logger.error(f"❌ Ошибка в AI-модели: {e}")

    logger.warning("⚠️ Используется fallback логика для оценки сигнала.")
    return fallback_score(result)

def fallback_score(result):
    signal = result.get("signal")
    rsi = result.get("rsi")
    macd = result.get("macd")
    patterns = result.get("patterns", [])
    score = 0.0

    if signal == "BUY" and rsi < 30:
        score += 0.3
    elif signal == "SELL" and rsi > 70:
        score += 0.3
    elif 45 <= rsi <= 55:
        score += 0.1

    if signal == "BUY" and macd > 0:
        score += 0.3
    elif signal == "SELL" and macd < 0:
        score += 0.3

    strong_bullish = ["hammer", "engulfing_bullish"]
    strong_bearish = ["shooting_star", "engulfing_bearish"]

    if signal == "BUY" and any(p in strong_bullish for p in patterns):
        score += 0.3
    elif signal == "SELL" and any(p in strong_bearish for p in patterns):
        score += 0.3

    score = round(score, 2)

    if score >= 0.8:
        logger.info(f"🔍 Ручной: Сильный сигнал {signal} с оценкой {score}")
    else:
        logger.info(f"ℹ️ Ручной: Слабый сигнал {signal} с оценкой {score}")
    return score
