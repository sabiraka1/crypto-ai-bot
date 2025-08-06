import pandas as pd
import numpy as np
import os
import joblib
import logging
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = "sinyal_fiyat_analizi.csv"
MODEL_DIR = "models"
MODEL_PATH = os.path.join(MODEL_DIR, "ai_model.pkl")
BACKUP_PATH = os.path.join(MODEL_DIR, "ai_model_backup.pkl")

def train_model():
    if not os.path.exists(DATA_FILE):
        logger.error("❌ Файл данных не найден!")
        return

    df = pd.read_csv(DATA_FILE)

    if df.shape[0] < 50:
        logger.warning("⚠️ Недостаточно данных для обучения.")
        return

    df = df.dropna()
    df = df[df['signal'].isin(["BUY", "SELL"])]
    df["signal_code"] = df["signal"].map({"BUY": 1, "SELL": -1})

    X = df[["rsi", "macd", "signal_code"]]
    y = df["success"].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # === Загрузка старой модели (если есть) ===
    old_accuracy = None
    if os.path.exists(MODEL_PATH):
        try:
            old_model = joblib.load(MODEL_PATH)
            y_pred_old = old_model.predict(X_test)
            old_accuracy = accuracy_score(y_test, y_pred_old)
            logger.info(f"📊 Точность старой модели: {old_accuracy:.4f}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при загрузке старой модели: {e}")

    # === Обучение новой модели ===
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    y_pred_new = model.predict(X_test)
    new_accuracy = accuracy_score(y_test, y_pred_new)
    logger.info(f"📈 Точность новой модели: {new_accuracy:.4f}")

    # === Сравнение ===
    if old_accuracy is not None and new_accuracy < old_accuracy:
        logger.warning("⛔ Новая модель хуже. Откат на старую.")
        return  # Не сохраняем новую модель
    else:
        if os.path.exists(MODEL_PATH):
            os.rename(MODEL_PATH, BACKUP_PATH)
            logger.info("📦 Старая модель перемещена в backup.")

        os.makedirs(MODEL_DIR, exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        logger.info("✅ Новая AI-модель сохранена.")

        # === Вывод важности признаков ===
        importances = model.feature_importances_
        for feature, imp in zip(X.columns, importances):
            logger.info(f"📌 Важность {feature}: {imp:.4f}")
