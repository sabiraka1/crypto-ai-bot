import os
import joblib
import pandas as pd
import numpy as np
import logging
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_PATH = "models/ai_model.pkl"
BACKUP_MODEL_PATH = "models/ai_model_old.pkl"
CSV_PATH = "sinyal_fiyat_analizi.xlsx"

def train_model():
    if not os.path.exists(CSV_PATH):
        logger.error(f"❌ Файл {CSV_PATH} не найден.")
        return

    # === Чтение данных ===
    df = pd.read_excel(CSV_PATH)
    df = df.dropna()

    features = ["rsi", "macd", "score", "stochrsi", "adx"]
    X = df[features]
    y = (df["result"] == "correct").astype(int)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # === Обучение новой модели ===
    new_model = RandomForestClassifier(n_estimators=100, random_state=42)
    new_model.fit(X_train, y_train)
    new_acc = accuracy_score(y_test, new_model.predict(X_test))

    logger.info(f"📈 Новая модель обучена. Accuracy: {new_acc:.2f}")

    # === Проверка старой модели (если есть) ===
    if os.path.exists(MODEL_PATH):
        try:
            old_model = joblib.load(MODEL_PATH)
            old_acc = accuracy_score(y_test, old_model.predict(X_test))
            logger.info(f"📉 Старая модель. Accuracy: {old_acc:.2f}")

            if new_acc >= old_acc:
                # Backup старой
                joblib.dump(old_model, BACKUP_MODEL_PATH)
                joblib.dump(new_model, MODEL_PATH)
                logger.info("✅ Новая модель заменяет старую. Backup сохранён.")
            else:
                logger.warning("⚠️ Новая модель хуже. Откат на старую модель.")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки старой модели: {e}")
            joblib.dump(new_model, MODEL_PATH)
            logger.info("✅ Сохранена только новая модель.")
    else:
        # Сохраняем впервые
        joblib.dump(new_model, MODEL_PATH)
        logger.info("✅ Модель сохранена впервые.")

    # === Важность признаков ===
    importances = new_model.feature_importances_
    logger.info("📊 Важность признаков:")
    for feat, imp in zip(features, importances):
        logger.info(f"  - {feat}: {imp:.4f}")
