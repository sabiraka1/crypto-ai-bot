import joblib
import os
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_PATH = "models/ai_model.pkl"
model = None

try:
    if os.path.exists(MODEL_PATH):
        model = joblib.load(MODEL_PATH)
        logger.info("✅ AI-модель успешно загружена.")
    else:
        logger.warning("⚠️ AI-модель не найдена. Используется fallback.")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки модели: {e}")

def encode_signal(signal):
    return {'BUY': 1, 'SELL': -1, 'HOLD': 0}.get(signal, 0)

def evaluate_signal(result):
    signal = result.get("signal")
    rsi = result.get("rsi")
    macd = result.get("macd")
    patterns = result.get("patterns", [])

    logger.info(f"🧪 Сигнал: {signal}, RSI: {rsi}, MACD: {macd}, Patterns: {patterns}")
    if model and signal and rsi is not None and macd is not None:
        try:
            signal_encoded = encode_signal(signal)
            input_data = np.array([[rsi, macd, signal_encoded]])
            prediction = model.predict_proba(input_data)[0][1]
            score = round(float(prediction), 2)
            logger.info(f"🤖 AI Score: {score}")
            return score
        except Exception as e:
            logger.error(f"❌ AI ошибка: {e}")

    return fallback_score(result)

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

    if signal == "BUY" and rsi < 30: score += 0.2
    if signal == "SELL" and rsi > 70: score += 0.2
    if signal == "BUY" and macd > 0: score += 0.2
    if signal == "SELL" and macd < 0: score += 0.2
    if signal == "BUY" and ema_signal == "bullish": score += 0.15
    if signal == "SELL" and ema_signal == "bearish": score += 0.15
    if signal == "BUY" and bollinger == "low": score += 0.1
    if signal == "SELL" and bollinger == "high": score += 0.1
    if adx and adx > 20: score += 0.1
    if signal == "BUY" and stochrsi < 20: score += 0.1
    if signal == "SELL" and stochrsi > 80: score += 0.1

    if signal == "BUY" and any(p in ["hammer", "engulfing_bullish"] for p in patterns):
        score += 0.1
    if signal == "SELL" and any(p in ["shooting_star", "engulfing_bearish"] for p in patterns):
        score += 0.1

    score = round(score, 2)
    logger.info(f"ℹ️ Fallback Score: {score}")
    return score
