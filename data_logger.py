import csv
import os
from datetime import datetime
from error_logger import log_error_signal

CSV_FILE = "sinyal_fiyat_analizi.csv"
CLOSED_FILE = "closed_trades.csv"

def log_trade(signal, score, price, rsi, macd, success):
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow([
                'datetime', 'signal', 'rsi', 'macd',
                'price', 'score', 'success'
            ])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signal, round(rsi, 2), round(macd, 2),
            round(price, 2), round(score, 2), int(success)
        ])

def log_test_trade(signal, score, price, rsi, macd):
    log_trade(signal, score, price, rsi, macd, success=False)

def log_closed_trade(entry_price, close_price, pnl_percent, reason, signal, score, rsi=None, macd=None):
    file_exists = os.path.isfile(CLOSED_FILE)
    with open(CLOSED_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow([
                'close_datetime', 'entry_price', 'close_price', 'pnl_percent',
                'reason', 'signal', 'ai_score'
            ])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            round(entry_price, 4), round(close_price, 4),
            round(pnl_percent * 100, 2),
            reason, signal, round(score, 2)
        ])

    if pnl_percent < 0 and rsi is not None and macd is not None:
        row = {
            "signal": signal,
            "score": score,
            "rsi": rsi,
            "macd": macd,
            "price": close_price,
            "pnl_percent": pnl_percent,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        log_error_signal(row)
