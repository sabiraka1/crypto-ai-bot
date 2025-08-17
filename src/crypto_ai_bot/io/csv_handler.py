# src/crypto_ai_bot/io/csv_handler.py
from __future__ import annotations
import csv
from typing import List, Dict, Any

def read_ohlcv_csv(path: str) -> List[Dict[str, Any]]:
    """
    Ожидаем заголовки: ts,open,high,low,close,volume
    Возвращаем список словарей с числовыми значениями.
    """
    out: List[Dict[str, Any]] = []
    with open(path, "r", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                out.append({
                    "ts_ms": int(row.get("ts") or row.get("timestamp") or row.get("time")),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0),
                })
            except Exception:
                continue
    return out
