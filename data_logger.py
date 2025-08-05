import csv
import os
from datetime import datetime

CSV_FILE = "sinyal_fiyat_analizi.csv"

def log_trade(signal, score, price, rsi, macd, success):
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['datetime', 'signal', 'rsi', 'macd', 'price', 'score', 'success'])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signal,
            round(rsi, 2),
            round(macd, 2),
            round(price, 2),
            round(score, 2),
            int(success)
        ])

def log_test_trade(signal, score, price, rsi, macd):
    # Для тестового сигнала success всегда False
    log_trade(signal, score, price, rsi, macd, success=False)
