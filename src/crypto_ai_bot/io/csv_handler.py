# src/crypto_ai_bot/io/csv_handler.py
from __future__ import annotations

from typing import Any, Dict, List
import csv

try:
    # используем наш надёжный парсер
    from crypto_ai_bot.backtest.csv_loader import load_ohlcv_csv as load_ohlcv_csv  # re-export
except Exception:
    def load_ohlcv_csv(path: str):
        raise RuntimeError("backtest.csv_loader not available")


def export_trades_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Унифицированная выгрузка сделок:
      поля: ts_ms, symbol, side, qty, price, pnl (опционально), note (опционально).
    """
    fields = ["ts_ms", "symbol", "side", "qty", "price", "pnl", "note"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
