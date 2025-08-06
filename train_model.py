import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib
import os

CSV_FILE = "sinyal_fiyat_analizi.csv"
MODEL_PATH = "models/ai_model.pkl"

def encode_signal(signal):
    return {'BUY': 1, 'SELL': -1, 'NONE': 0}.get(signal, 0)

def train_model():
    if not os.path.exists(CSV_FILE):
        print("⚠️ CSV-файл не найден. Обучение невозможно.")
        return

    df = pd.read_csv(CSV_FILE)

    if len(df) < 10:
        print("⚠️ Недостаточно данных для обучения модели.")
        return

    # Преобразование признаков
    df["signal_encoded"] = df["signal"].apply(encode_signal)
    df["target"] = df["success"].astype(int)

    X = df[["rsi", "macd", "signal_encoded"]]
    y = df["target"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"✅ Модель обучена. Accuracy: {acc:.2f}")

    # Сохраняем
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print("💾 Модель сохранена:", MODEL_PATH)
