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
        logger.warning("⚠️ AI-модель не найдена. Создается базовая модель...")
        # Создаем базовую модель если её нет
        from generate_model import create_model
        create_model()
        if os.path.exists(MODEL_PATH):
            model = joblib.load(MODEL_PATH)
            logger.info("✅ Базовая AI-модель создана и загружена.")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки модели: {e}")

def encode_signal(signal):
    """Кодирует сигналы для модели"""
    mapping = {
        'BUY': 1, 'STRONG_BUY': 1.5, 
        'SELL': -1, 'STRONG_SELL': -1.5, 
        'HOLD': 0, 'ERROR': 0
    }
    return mapping.get(signal, 0)

def encode_pattern_direction(direction):
    """Кодирует направление паттерна"""
    mapping = {
        'BULLISH': 1, 'BEARISH': -1, 
        'REVERSAL': 0.5, 'INDECISION': 0, 
        'NEUTRAL': 0
    }
    return mapping.get(direction, 0)

def evaluate_signal(result):
    """Оценивает сигнал с помощью AI модели и fallback логики"""
    signal = result.get("signal", "HOLD")
    rsi = result.get("rsi", 50)
    macd = result.get("macd", 0)
    pattern = result.get("pattern", "NONE")
    pattern_score = result.get("pattern_score", 0)
    pattern_direction = result.get("pattern_direction", "NEUTRAL")
    confidence = result.get("confidence", 0)
    buy_score = result.get("buy_score", 0)
    sell_score = result.get("sell_score", 0)

    logger.info(f"🧪 Анализ: {signal} | RSI: {rsi:.1f} | MACD: {macd:.4f} | Pattern: {pattern} | Confidence: {confidence:.1f}%")
    
    # Попытка использовать AI модель
    if model and signal and rsi is not None and macd is not None:
        try:
            signal_encoded = encode_signal(signal)
            pattern_dir_encoded = encode_pattern_direction(pattern_direction)
            
            # Расширенные входные данные для модели
            input_data = np.array([[
                rsi, macd, signal_encoded, 
                pattern_score, pattern_dir_encoded,
                confidence, buy_score, sell_score
            ]])
            
            prediction = model.predict_proba(input_data)[0]
            # Берем вероятность успешного сигнала
            ai_score = round(float(prediction[1] if len(prediction) > 1 else prediction[0]), 3)
            
            logger.info(f"🤖 AI Score: {ai_score}")
            return ai_score
            
        except Exception as e:
            logger.warning(f"⚠️ AI модель недоступна, используется fallback: {e}")

    # Fallback оценка
    return fallback_score(result)

def fallback_score(result):
    """Продвинутая fallback логика оценки сигналов"""
    signal = result.get("signal", "HOLD")
    rsi = result.get("rsi", 50)
    macd = result.get("macd", 0)
    pattern = result.get("pattern", "NONE")
    pattern_score = result.get("pattern_score", 0)
    pattern_direction = result.get("pattern_direction", "NEUTRAL")
    confidence = result.get("confidence", 0)
    buy_score = result.get("buy_score", 0)
    sell_score = result.get("sell_score", 0)
    support = result.get("support", 0)
    resistance = result.get("resistance", 0)
    price = result.get("price", 0)

    score = 0.0

    # Базовая оценка по сигналу и confidence
    if signal in ["BUY", "STRONG_BUY"]:
        score += 0.3
        if signal == "STRONG_BUY":
            score += 0.2
    elif signal in ["SELL", "STRONG_SELL"]:
        score += 0.3
        if signal == "STRONG_SELL":
            score += 0.2

    # Оценка по confidence
    score += (confidence / 100) * 0.3

    # RSI анализ
    if signal in ["BUY", "STRONG_BUY"] and rsi < 35:
        score += 0.15
    elif signal in ["SELL", "STRONG_SELL"] and rsi > 65:
        score += 0.15
    elif 35 <= rsi <= 65:  # Нейтральная зона
        score += 0.05

    # MACD анализ
    if signal in ["BUY", "STRONG_BUY"] and macd > 0:
        score += 0.1
    elif signal in ["SELL", "STRONG_SELL"] and macd < 0:
        score += 0.1

    # Анализ паттернов
    if pattern_score >= 4:
        score += 0.1
        if pattern_score >= 6:
            score += 0.05
    
    # Соответствие направления паттерна и сигнала
    if (signal in ["BUY", "STRONG_BUY"] and pattern_direction == "BULLISH") or \
       (signal in ["SELL", "STRONG_SELL"] and pattern_direction == "BEARISH"):
        score += 0.1

    # Анализ уровней поддержки/сопротивления
    if support > 0 and resistance > 0 and price > 0:
        if signal in ["BUY", "STRONG_BUY"] and price <= support * 1.01:  # Рядом с поддержкой
            score += 0.1
        elif signal in ["SELL", "STRONG_SELL"] and price >= resistance * 0.99:  # Рядом с сопротивлением
            score += 0.1

    # Анализ количества выполненных условий
    if buy_score >= 5 or sell_score >= 5:
        score += 0.1
    elif buy_score >= 3 or sell_score >= 3:
        score += 0.05

    # Нормализуем score в диапазон 0-1
    score = min(max(score, 0), 1)
    score = round(score, 3)
    
    logger.info(f"ℹ️ Fallback Score: {score}")
    return score

def should_trade(signal, score, min_score=0.65):
    """Определяет, стоит ли торговать по данному сигналу"""
    if signal in ["ERROR", "HOLD"]:
        return False
    
    if signal in ["STRONG_BUY", "STRONG_SELL"]:
        return score >= (min_score - 0.1)  # Более низкий порог для сильных сигналов
    
    return score >= min_score
