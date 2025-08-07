import pandas as pd
import numpy as np
import joblib
import os
import logging
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import matplotlib.pyplot as plt

MODEL_PATH = "models/ai_model.pkl"
OLD_MODEL_PATH = "models/ai_model_backup.pkl"
CSV_FILE = "sinyal_fiyat_analizi.xlsx"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_data():
    df = pd.read_excel(CSV_FILE)
    df = df.dropna(subset=["signal", "rsi", "macd", "result"])
    df["signal_encoded"] = df["signal"].map({"BUY": 1, "SELL": -1, "NONE": 0}).fillna(0)
    df["result_encoded"] = df["result"].map({"UP": 1, "DOWN": 0}).fillna(0)
    df["ema_signal_encoded"] = df["ema_signal"].map({"bullish": 1, "bearish": -1}).fillna(0)
    df["bollinger_encoded"] = df["bollinger"].map({"low": 1, "high": -1}).fillna(0)

    features = [
        "rsi", "macd", "signal_encoded",
        "stochrsi", "adx", "ema_signal_encoded", "bollinger_encoded"
    ]
    target = "result_encoded"

    return df[features], df[target], features

def train_model():
    X, y, feature_names = load_data()

    if len(X) < 20:
        logger.warning("⚠️ Недостаточно данных для обучения модели!")
        return

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    new_model = RandomForestClassifier(n_estimators=100, random_state=42)
    new_model.fit(X_train, y_train)

    y_pred = new_model.predict(X_test)
    new_acc = accuracy_score(y_test, y_pred)
    logger.info(f"📈 Точность новой модели: {new_acc:.2f}")

    old_acc = 0
    if os.path.exists(MODEL_PATH):
        try:
            old_model = joblib.load(MODEL_PATH)
            y_pred_old = old_model.predict(X_test)
            old_acc = accuracy_score(y_test, y_pred_old)
            logger.info(f"📉 Точность старой модели: {old_acc:.2f}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при проверке старой модели: {e}")

    if new_acc >= old_acc:
        if os.path.exists(MODEL_PATH):
            os.rename(MODEL_PATH, OLD_MODEL_PATH)
            logger.info("🗂️ Старая модель сохранена как резервная.")

        joblib.dump(new_model, MODEL_PATH)
        logger.info("✅ Новая AI-модель сохранена.")
    else:
        logger.warning("❌ Новая модель хуже! Старая оставлена.")

    importances = new_model.feature_importances_
    logger.info("📊 Важность признаков:")
    for name, score in zip(feature_names, importances):
        logger.info(f"{name}: {score:.2f}")

    plt.figure(figsize=(10, 4))
    plt.bar(feature_names, importances, color='green')
    plt.title("Feature Importance")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("charts/feature_importance.png")
    logger.info("📉 График важности признаков сохранён в charts/feature_importance.png")

# 🔁 Для Telegram: функция переобучения
def retrain_model():
    logger.info("🔁 Старт переобучения модели...")
    train_model()
    logger.info("✅ Переобучение завершено!")

if __name__ == "__main__":
    train_model()
