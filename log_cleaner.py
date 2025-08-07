import pandas as pd
import os
from datetime import datetime, timedelta

SIGNAL_CSV = "sinyal_fiyat_analizi.csv"
CLOSED_CSV = "closed_trades.csv"

def clean_csv(file_path, date_column, days=60):
    if not os.path.exists(file_path):
        return

    try:
        df = pd.read_csv(file_path)
        if date_column not in df.columns:
            return
        df[date_column] = pd.to_datetime(df[date_column])
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df[date_column] >= cutoff]
        df.to_csv(file_path, index=False)
        print(f"🧹 {file_path} очищен — осталось {len(df)} строк")
    except Exception as e:
        print(f"❌ Ошибка при очистке {file_path}: {e}")

def clean_logs():
    clean_csv(SIGNAL_CSV, "datetime")
    clean_csv(CLOSED_CSV, "close_datetime")

if __name__ == "__main__":
    clean_logs()
