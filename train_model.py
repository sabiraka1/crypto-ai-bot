import pandas as pd
import numpy as np
import joblib
import os
import logging
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import matplotlib.pyplot as plt

MODEL_PATH = "models/ai_model.pkl"
OLD_MODEL_PATH = "models/ai_model_backup.pkl"
CSV_FILE = "sinyal_fiyat_analizi.csv"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_data():
    """Загрузка и подготовка данных для обучения"""
    if not os.path.exists(CSV_FILE):
        logger.warning(f"⚠️ Файл {CSV_FILE} не найден")
        return None, None, None
    
    try:
        df = pd.read_csv(CSV_FILE)
        logger.info(f"📊 Загружено {len(df)} записей")
        
        # Проверяем наличие необходимых колонок
        required_cols = ["signal", "rsi", "macd", "success"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            logger.error(f"❌ Отсутствуют колонки: {missing_cols}")
            return None, None, None
        
        # Очистка данных
        df = df.dropna(subset=required_cols)
        
        if len(df) < 10:
            logger.warning(f"⚠️ Недостаточно данных: {len(df)} записей")
            return None, None, None
        
        # УБРАНА проблемная строка с ema_signal!
        
        # Кодирование признаков
        df["signal_encoded"] = df["signal"].map({
            "BUY": 1, "STRONG_BUY": 1.5, 
            "SELL": -1, "STRONG_SELL": -1.5, 
            "CRITICAL_SELL": -2,
            "HOLD": 0, "WAIT": 0, "NONE": 0, "ERROR": 0
        }).fillna(0)
        
        df["result_encoded"] = df["success"].astype(int)
        
        # Дополнительные признаки если они есть
        feature_cols = ["rsi", "macd", "signal_encoded"]
        
        # Добавляем дополнительные признаки если они существуют
        optional_features = [
            "pattern_score", "confidence", "buy_score", "sell_score",
            "total_score", "macd_contribution", "ai_score",
            "price_change_24h", "macd_histogram"
        ]
        
        for feat in optional_features:
            if feat in df.columns:
                df[feat] = pd.to_numeric(df[feat], errors='coerce').fillna(0)
                feature_cols.append(feat)
                logger.info(f"✅ Добавлен признак: {feat}")
        
        # Кодирование паттернов если есть
        if "pattern_direction" in df.columns:
            df["pattern_direction_encoded"] = df["pattern_direction"].map({
                "BULLISH": 1, "BEARISH": -1, "REVERSAL": 0.5, 
                "INDECISION": 0, "NEUTRAL": 0
            }).fillna(0)
            feature_cols.append("pattern_direction_encoded")
            logger.info("✅ Добавлено кодирование pattern_direction")
        
        # Кодирование трендов для Enhanced системы
        if "trend_1d" in df.columns:
            df["trend_1d_encoded"] = df["trend_1d"].map({
                "BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0, "UNKNOWN": 0
            }).fillna(0)
            feature_cols.append("trend_1d_encoded")
            logger.info("✅ Добавлено кодирование trend_1d")
            
        if "trend_4h" in df.columns:
            df["trend_4h_encoded"] = df["trend_4h"].map({
                "BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0, "UNKNOWN": 0
            }).fillna(0)
            feature_cols.append("trend_4h_encoded")
            logger.info("✅ Добавлено кодирование trend_4h")
        
        if "market_state" in df.columns:
            df["market_state_encoded"] = df["market_state"].map({
                "NORMAL": 0, "HIGH_VOLATILITY": 0.5, 
                "OVERHEATED_BULLISH": 1, "OVERSOLD_BEARISH": -1,
                "OVERHEATED": 1
            }).fillna(0)
            feature_cols.append("market_state_encoded")
            logger.info("✅ Добавлено кодирование market_state")
        
        X = df[feature_cols]
        y = df["result_encoded"]
        
        logger.info(f"📈 Признаки ({len(feature_cols)}): {feature_cols}")
        logger.info(f"📊 Распределение классов: {y.value_counts().to_dict()}")
        
        return X, y, feature_cols
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки данных: {e}")
        logger.error(f"❌ Доступные колонки: {list(df.columns) if 'df' in locals() else 'N/A'}")
        return None, None, None

def train_model():
    """Обучение модели машинного обучения"""
    logger.info("🧠 Начинаю обучение модели...")
    
    X, y, feature_names = load_data()
    
    if X is None or len(X) < 20:
        logger.warning("⚠️ Недостаточно данных для обучения модели!")
        
        # Создаем базовую модель если данных мало
        if not os.path.exists(MODEL_PATH):
            create_basic_model()
        return
    
    try:
        # Разделение данных с защитой от ошибок
        stratify_param = y if len(y.unique()) > 1 else None
        test_size = min(0.2, max(0.1, 10 / len(X)))  # Адаптивный размер теста
        
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=stratify_param
        )
        
        # Обучение новой модели
        new_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1  # Использовать все ядра
        )
        
        new_model.fit(X_train, y_train)
        
        # Оценка новой модели
        y_pred = new_model.predict(X_test)
        new_acc = accuracy_score(y_test, y_pred)
        logger.info(f"📈 Точность новой модели: {new_acc:.3f}")
        
        # Проверка старой модели
        old_acc = 0
        if os.path.exists(MODEL_PATH):
            try:
                old_model = joblib.load(MODEL_PATH)
                # Проверка совместимости признаков
                if hasattr(old_model, 'n_features_in_') and old_model.n_features_in_ == X_test.shape[1]:
                    y_pred_old = old_model.predict(X_test)
                    old_acc = accuracy_score(y_test, y_pred_old)
                    logger.info(f"📉 Точность старой модели: {old_acc:.3f}")
                else:
                    logger.warning("⚠️ Старая модель несовместима - будет заменена")
                    old_acc = 0
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при проверке старой модели: {e}")
        
        # Сохранение модели если она лучше
        if new_acc >= old_acc or not os.path.exists(MODEL_PATH):
            # Резервное копирование старой модели
            if os.path.exists(MODEL_PATH):
                try:
                    os.rename(MODEL_PATH, OLD_MODEL_PATH)
                    logger.info("🗂️ Старая модель сохранена как резервная")
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка резервного копирования: {e}")
            
            # Сохранение новой модели
            os.makedirs("models", exist_ok=True)
            joblib.dump(new_model, MODEL_PATH)
            logger.info("✅ Новая AI-модель сохранена")
            
            # Детальный отчет
            try:
                logger.info("\n" + classification_report(y_test, y_pred))
            except Exception as e:
                logger.warning(f"⚠️ Ошибка отчета: {e}")
            
        else:
            logger.warning("❌ Новая модель хуже старой - оставляем старую")
        
        # Анализ важности признаков
        try:
            importances = new_model.feature_importances_
            logger.info("📊 Важность признаков:")
            for name, score in zip(feature_names, importances):
                logger.info(f"  {name}: {score:.3f}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка анализа важности: {e}")
        
        # Создание графика важности признаков
        try:
            plt.figure(figsize=(12, 6))
            plt.bar(feature_names, importances, color='green', alpha=0.7)
            plt.title("🔍 Важность признаков модели")
            plt.xlabel("Признаки")
            plt.ylabel("Важность")
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            # Сохранение графика
            os.makedirs("charts", exist_ok=True)
            plt.savefig("charts/feature_importance.png", dpi=300, bbox_inches='tight')
            plt.close()
            logger.info("📊 График важности признаков сохранен")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка создания графика: {e}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка обучения модели: {e}")

def create_basic_model():
    """Создание базовой модели с примерными данными"""
    logger.info("🏗️ Создание базовой модели...")
    
    try:
        # Примерные данные для начального обучения
        data = {
            "rsi": [25, 70, 45, 80, 30, 65, 50, 40, 60, 35, 75, 28, 55, 85, 20],
            "macd": [0.5, -0.3, 0.1, -0.4, 0.6, -0.2, 0.0, 0.3, -0.1, 0.4, -0.5, 0.7, 0.2, -0.6, 0.8],
            "signal": ["BUY", "SELL", "HOLD", "SELL", "BUY", "SELL", "HOLD", "BUY", "SELL", "BUY", "SELL", "BUY", "HOLD", "SELL", "BUY"],
            "success": [1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1]
        }
        
        df = pd.DataFrame(data)
        df["signal_encoded"] = df["signal"].map({"BUY": 1, "SELL": -1, "HOLD": 0})
        df["pattern_score"] = np.random.uniform(0, 6, len(df))
        df["confidence"] = np.random.uniform(20, 90, len(df))
        df["total_score"] = np.random.uniform(0, 5, len(df))
        df["macd_contribution"] = np.random.uniform(0, 3, len(df))
        df["ai_score"] = np.random.uniform(0.1, 0.9, len(df))
        
        feature_cols = ["rsi", "macd", "signal_encoded", "pattern_score", "confidence", 
                       "total_score", "macd_contribution", "ai_score"]
        X = df[feature_cols]
        y = df["success"]
        
        # Обучение базовой модели
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        model.fit(X, y)
        
        # Сохранение модели
        os.makedirs("models", exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        logger.info("✅ Базовая модель создана и сохранена")
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания базовой модели: {e}")

def retrain_model():
    """Функция для переобучения модели (вызывается из телеграм бота)"""
    logger.info("🔁 Переобучение AI-модели...")
    try:
        train_model()
        logger.info("✅ Переобучение завершено успешно")
    except Exception as e:
        logger.error(f"❌ Ошибка переобучения: {e}")
        # НЕ поднимаем исключение, чтобы не крашить бота
        logger.info("⚠️ Продолжаем работу со старой моделью")

def get_model_info():
    """Получение информации о текущей модели"""
    if not os.path.exists(MODEL_PATH):
        return "❌ Модель не найдена"
    
    try:
        model = joblib.load(MODEL_PATH)
        
        # Базовая информация
        info = {
            "type": type(model).__name__,
            "n_estimators": getattr(model, 'n_estimators', 'N/A'),
            "max_depth": getattr(model, 'max_depth', 'N/A'),
            "n_features": getattr(model, 'n_features_in_', 'N/A')
        }
        
        return info
        
    except Exception as e:
        return f"❌ Ошибка чтения модели: {e}"

if __name__ == "__main__":
    train_model()
