import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import joblib
import os

print("🚀 Модель создаётся... Пожалуйста, подождите.")

# Примерные данные
data = {
    "rsi": [25, 70, 45, 80, 30, 65, 50, 40, 60, 35],
    "macd": [0.5, -0.3, 0.1, -0.4, 0.6, -0.2, 0.0, 0.3, -0.1, 0.4],
    "signal": ["BUY", "SELL", "NONE", "SELL", "BUY", "SELL", "NONE", "BUY", "SELL", "BUY"],
    "success": [1, 0, 1, 0, 1, 0, 1, 1, 0, 1]
}

df = pd.DataFrame(data)
df["signal_encoded"] = df["signal"].map({"BUY": 1, "SELL": -1, "NONE": 0})
X = df[["rsi", "macd", "signal_encoded"]]
y = df["success"]

model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X, y)

# Создание директории, если нет
os.makedirs("models", exist_ok=True)
joblib.dump(model, "models/ai_model.pkl")

print("✅ Модель сохранена в models/ai_model.pkl")
