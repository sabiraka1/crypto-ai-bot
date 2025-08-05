import csv
import os
from datetime import datetime

CSV_FILE = "sinyal_fiyat_analizi.csv"

def log_trade(signal, score, price, success):
    """
    Логирует торговый сигнал в CSV файл:
    - signal: BUY / SELL / NONE
    - score: AI оценка (0.0 – 1.0)
    - price: текущая цена BTC/USDT
    - success: 1 (успешно) или 0 (тест/не выполнено)
    """
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['datetime', 'signal', 'rsi', 'macd', 'price', 'score', 'success'])

        # Примерные значения RSI/MACD (если нет настоящих)
        rsi = 30 if signal == 'BUY' else 70 if signal == 'SELL' else 50
        macd = 0.5 if signal == 'BUY' else -0.5 if signal == 'SELL' else 0

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signal,
            rsi,
            macd,
            price,
            round(score, 2),
            int(success)
        ])

def log_test_trade(signal, score, price):
    """
    Логирует тестовый сигнал (без реальной сделки).
    """
    log_trade(signal, score, price, success=False)
