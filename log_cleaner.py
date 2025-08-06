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
            print(f"⚠️ Нет колонки {date_column} в {file_path}")
            return

        df[date_column] = pd.to_datetime(df[date_column])
        cutoff_date = datetime.now() - timedelta(days=days)
        df_filtered = df[df[date_column] >= cutoff_date]

        df_filtered.to_csv(file_path, index=False)
        print(f"🧹 Очищен файл {file_path}: осталось строк — {len(df_filtered)}")

    except Exception as e:
        print(f"❌ Ошибка при очистке {file_path}: {e}")


def clean_logs():
    clean_csv(SIGNAL_CSV, date_column="datetime", days=60)
    clean_csv(CLOSED_CSV, date_column="close_datetime", days=60)


if __name__ == "__main__":
    clean_logs()
