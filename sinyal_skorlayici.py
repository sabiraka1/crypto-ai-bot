import joblib
import os
import numpy as np

# === Загрузка модели ===
MODEL_PATH = "models/ai_model.pkl"
model = None

if os.path.exists(MODEL_PATH):
    model = joblib.load(MODEL_PATH)
    print("✅ AI-модель успешно загружена.")
else:
    print("⚠️ AI-модель не найдена. Сигналы будут оцениваться вручную.")

# === Преобразование текста сигнала в число ===
def encode_signal(signal):
    return {'BUY': 1, 'SELL': -1, 'NONE': 0}.get(signal, 0)

# === Основная функция ===
def evaluate_signal(result):
    signal = result.get("signal")
    rsi = result.get("rsi")
    macd = result.get("macd")
    
    if model and signal is not None and rsi is not None and macd is not None:
        signal_encoded = encode_signal(signal)
        input_data = np.array([[rsi, macd, signal_encoded]])
        
        try:
            prediction = model.predict_proba(input_data)[0][1]  # вероятность успеха
            score = round(float(prediction), 2)

            if score >= 0.8:
                print(f"🤖 AI: Сильный сигнал {signal} с оценкой {score}")
            else:
                print(f"🤖 AI: Слабый/нейтральный сигнал {signal} с оценкой {score}")
            
            return score
        except Exception as e:
            print(f"❌ Ошибка в AI-модели: {e}")

    # Фоллбэк — ручной расчёт
    print("⚠️ Используется fallback логика для оценки сигнала.")
    return fallback_score(result)

# === Ручная логика, как была раньше ===
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
        print(f"🔍 Ручной: Сильный сигнал {signal} с оценкой {score}")
    else:
        print(f"ℹ️ Ручной: Слабый сигнал {signal} с оценкой {score}")
    return score
