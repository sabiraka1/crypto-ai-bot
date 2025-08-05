import csv
import os
from datetime import datetime

CSV_FILE = "sinyal_fiyat_analizi.csv"

def log_trade(signal, score, price, success):
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['datetime', 'signal', 'rsi', 'macd', 'price', 'score', 'success'])

        rsi = 30 if signal == 'BUY' else 70 if signal == 'SELL' else 50
        macd = 0.5 if signal == 'BUY' else -0.5 if signal == 'SELL' else 0

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signal,
            rsi,
            macd,
            price,
            score,
            int(success)
        ])
