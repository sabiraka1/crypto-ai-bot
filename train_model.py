import pandas as pd
import os
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

CSV_FILE = "sinyal_fiyat_analizi.csv"
MODEL_PATH = "models/ai_model.pkl"

# Убедись, что папка models существует
os.makedirs("models", exist_ok=True)

# Загрузка и подготовка данных
df = pd.read_csv(CSV_FILE)
df.dropna(inplace=True)

# Кодируем текстовые сигналы
df['signal_encoded'] = df['signal'].map({'BUY': 1, 'SELL': -1, 'NONE': 0})
df['success'] = df['success'].astype(int)

# Признаки и целевая переменная
X = df[['rsi', 'macd', 'signal_encoded']]
y = df['success']

# Разделение на train/test
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Обучение модели
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Сохранение
joblib.dump(model, MODEL_PATH)
print(f"✅ Модель сохранена в {MODEL_PATH}")
