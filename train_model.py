import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import pickle
import os

CSV_FILE = "sinyal_fiyat_analizi.csv"
MODEL_PATH = "models/ai_model.pkl"

def train_model():
    if not os.path.exists(CSV_FILE):
        print("❌ Файл с сигналами не найден.")
        return

    df = pd.read_csv(CSV_FILE)

    if len(df) < 30:
        print("ℹ️ Недостаточно данных для обучения модели (нужно хотя бы 30 строк).")
        return

    # 🎯 Целевая переменная
    df['target'] = df['success']

    # 🧠 Фичи для обучения
    X = df[['rsi', 'macd', 'score']]
    y = df['target']

    # 📚 Разделение данных
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # 🤖 Модель
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    # 💾 Сохранение модели
    os.makedirs("models", exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    print("✅ Модель переобучена и сохранена.")
