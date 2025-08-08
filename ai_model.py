import os
import pandas as pd
import pickle
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from dotenv import load_dotenv

load_dotenv()

MODEL_FILE = "model.pkl"
DATA_FILE = "sinyal_fiyat_analizi.csv"

def load_data():
    if not os.path.exists(DATA_FILE):
        return None, None
    df = pd.read_csv(DATA_FILE)
    if len(df) < 50:  # Минимум данных для обучения
        return None, None
    # Фичи — RSI, MACD, PatternScore
    X = df[["rsi", "macd", "pattern_score"]]
    y = df["result"]  # 1 — прибыльно, 0 — нет
    return X, y

def train_model():
    X, y = load_data()
    if X is None:
        return None

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"📊 Модель обучена, точность: {acc:.2f}")

    with open(MODEL_FILE, "wb") as f:
        pickle.dump(model, f)

    return model

def retrain_model():
    print("♻ Переобучение модели...")
    return train_model()

def predict_signal_strength(rsi, macd, pattern_score):
    if not os.path.exists(MODEL_FILE):
        model = train_model()
        if model is None:
            return 0.5  # Среднее значение
    else:
        with open(MODEL_FILE, "rb") as f:
            model = pickle.load(f)

    df = pd.DataFrame([[rsi, macd, pattern_score]], columns=["rsi", "macd", "pattern_score"])
    prob = model.predict_proba(df)[0][1]
    return round(prob, 3)
