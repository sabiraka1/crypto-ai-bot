import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import joblib
import os

def create_model():
    """Создание базовой AI модели с расширенными признаками"""
    print("💡 Создание базовой AI модели...")
    
    # Расширенные примерные данные для лучшего обучения
    np.random.seed(42)
    n_samples = 100
    
    data = {
        "rsi": np.random.uniform(10, 90, n_samples),
        "macd": np.random.uniform(-200, 200, n_samples),
        "signal_encoded": np.random.choice([-1.5, -1, 0, 1, 1.5], n_samples),
        "pattern_score": np.random.uniform(0, 10, n_samples),
        "pattern_direction_encoded": np.random.choice([-1, -0.5, 0, 0.5, 1], n_samples),
        "confidence": np.random.uniform(20, 95, n_samples),
        "buy_score": np.random.randint(0, 9, n_samples),
        "sell_score": np.random.randint(0, 9, n_samples)
    }
    
    df = pd.DataFrame(data)
    
    # Логика для определения успешности (более реалистичная)
    success_probability = 0.5  # базовая вероятность
    
    # Увеличиваем вероятность успеха для хороших условий
    for i in range(len(df)):
        prob = success_probability
        
        # RSI условия
        if 30 <= df.loc[i, 'rsi'] <= 70:
            prob += 0.1
        elif df.loc[i, 'rsi'] < 25 or df.loc[i, 'rsi'] > 75:
            prob -= 0.1
            
        # Confidence
        if df.loc[i, 'confidence'] > 70:
            prob += 0.15
        elif df.loc[i, 'confidence'] < 40:
            prob -= 0.15
            
        # Pattern score
        if df.loc[i, 'pattern_score'] > 6:
            prob += 0.1
        elif df.loc[i, 'pattern_score'] < 3:
            prob -= 0.1
            
        # MACD и signal согласованность
        if (df.loc[i, 'signal_encoded'] > 0 and df.loc[i, 'macd'] > 0) or \
           (df.loc[i, 'signal_encoded'] < 0 and df.loc[i, 'macd'] < 0):
            prob += 0.1
        else:
            prob -= 0.05
            
        df.loc[i, 'success'] = 1 if np.random.random() < prob else 0
    
    # Подготовка данных для обучения
    features = ["rsi", "macd", "signal_encoded", "pattern_score", 
                "pattern_direction_encoded", "confidence", "buy_score", "sell_score"]
    
    X = df[features]
    y = df["success"]
    
    # Обучение модели
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42
    )
    
    model.fit(X, y)
    
    # Создание директории и сохранение
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, "models/ai_model.pkl")
    
    # Информация о модели
    accuracy = model.score(X, y)
    print(f"✅ Базовая модель создана с точностью: {accuracy:.3f}")
    print(f"📊 Признаки: {features}")
    print(f"📈 Успешных сигналов: {sum(y)}/{len(y)} ({sum(y)/len(y)*100:.1f}%)")
    print("✅ Модель сохранена в models/ai_model.pkl")

def create_advanced_model():
    """Создание продвинутой модели с более сложной логикой"""
    print("🚀 Создание продвинутой AI модели...")
    
    # Генерируем больше данных с более сложными паттернами
    np.random.seed(123)
    n_samples = 500
    
    # Создаем более реалистичные данные
    rsi_values = []
    macd_values = []
    signals = []
    pattern_scores = []
    confidences = []
    successes = []
    
    for i in range(n_samples):
        # Генерируем RSI с трендами
        if i < n_samples // 3:  # Медвежий тренд
            rsi = np.random.normal(60, 15)
            signal = np.random.choice([-1, -1.5, 0], p=[0.4, 0.3, 0.3])
        elif i < 2 * n_samples // 3:  # Бычий тренд
            rsi = np.random.normal(40, 15)
            signal = np.random.choice([1, 1.5, 0], p=[0.4, 0.3, 0.3])
        else:  # Боковой тренд
            rsi = np.random.normal(50, 10)
            signal = np.random.choice([-1, 0, 1], p=[0.3, 0.4, 0.3])
        
        rsi = np.clip(rsi, 5, 95)
        
        # MACD коррелирует с трендом
        macd = np.random.normal(signal * 50, 100)
        
        # Pattern score зависит от согласованности
        if (signal > 0 and rsi < 50) or (signal < 0 and rsi > 50):
            pattern_score = np.random.uniform(4, 9)  # Хорошие паттерны
        else:
            pattern_score = np.random.uniform(0, 5)  # Слабые паттерны
        
        # Confidence основана на множественных факторах
        confidence = 50
        if abs(signal) > 1:  # STRONG сигналы
            confidence += 20
        if pattern_score > 6:
            confidence += 15
        if (signal > 0 and rsi < 35) or (signal < 0 and rsi > 65):
            confidence += 10
        
        confidence = np.clip(confidence + np.random.normal(0, 10), 20, 95)
        
        # Успешность зависит от качества сигнала
        success_prob = 0.5
        if confidence > 70:
            success_prob += 0.2
        if pattern_score > 6:
            success_prob += 0.15
        if (signal > 0 and macd > 0) or (signal < 0 and macd < 0):
            success_prob += 0.1
        
        success = 1 if np.random.random() < success_prob else 0
        
        rsi_values.append(rsi)
        macd_values.append(macd)
        signals.append(signal)
        pattern_scores.append(pattern_score)
        confidences.append(confidence)
        successes.append(success)
    
    # Создаем DataFrame
    df = pd.DataFrame({
        "rsi": rsi_values,
        "macd": macd_values,
        "signal_encoded": signals,
        "pattern_score": pattern_scores,
        "pattern_direction_encoded": [np.random.choice([-1, 0, 1]) for _ in range(n_samples)],
        "confidence": confidences,
        "buy_score": np.random.randint(0, 9, n_samples),
        "sell_score": np.random.randint(0, 9, n_samples),
        "success": successes
    })
    
    # Обучение модели
    features = ["rsi", "macd", "signal_encoded", "pattern_score", 
                "pattern_direction_encoded", "confidence", "buy_score", "sell_score"]
    
    X = df[features]
    y = df["success"]
    
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=15,
        min_samples_split=10,
        min_samples_leaf=3,
        random_state=42
    )
    
    model.fit(X, y)
    
    # Сохранение
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, "models/ai_model.pkl")
    
    accuracy = model.score(X, y)
    win_rate = sum(y) / len(y) * 100
    
    print(f"✅ Продвинутая модель создана!")
    print(f"📊 Точность: {accuracy:.3f}")
    print(f"📈 Win Rate: {win_rate:.1f}%")
    print(f"📋 Образцов: {len(df)}")

if __name__ == "__main__":
    # Можно выбрать какую модель создавать
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "advanced":
        create_advanced_model()
    else:
        create_model()
