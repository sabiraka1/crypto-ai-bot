import pandas as pd
from sklearn.linear_model import LogisticRegression
import os

# Путь к CSV с историей сигналов
CSV_FILE = "sinyal_fiyat_analizi.csv"

def evaluate_signal(signal_data):
    if not os.path.exists(CSV_FILE):
        return 0.5  # Нет данных? Возвращаем нейтральную оценку

    df = pd.read_csv(CSV_FILE)
    if len(df) < 10:
        return 0.5  # Мало данных — доверие низкое

    X = df[['rsi', 'macd', 'price']]  # Признаки
    y = df['success']                 # Целевая переменная

    model = LogisticRegression()
    model.fit(X, y)

    # Текущий сигнал:
    rsi = signal_data.get('rsi', 50)
    macd = signal_data.get('macd', 0)
    price = signal_data.get('price', 10000)

    prob = model.predict_proba([[rsi, macd, price]])[0][1]
    return round(prob, 2)
