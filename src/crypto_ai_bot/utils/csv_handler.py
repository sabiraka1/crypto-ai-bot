# src/crypto_ai_bot/utils/csv_handler.py
"""
🗂️ CSVHandler — безопасная запись CSV-логов (без внешних зависимостей)
- Лог закрытых сделок: CLOSED_TRADES_CSV (из Settings)
- Авто-создание папок и заголовка
"""

from __future__ import annotations

import os
import csv
import threading
from typing import Dict, Any

from crypto_ai_bot.config.settings import Settings


class CSVHandler:
    _lock = threading.RLock()

    @staticmethod
    def _ensure_parent(path: str) -> None:
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        except Exception:
            pass

    @staticmethod
    def _ensure_header(path: str, fieldnames) -> None:
        exists = os.path.exists(path)
        if not exists or os.path.getsize(path) == 0:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

    @classmethod
    def log_close_trade(cls, row: Dict[str, Any]) -> None:
        cfg = Settings.load()
        path = getattr(cfg, "CLOSED_TRADES_CSV", os.path.join("data", "closed_trades.csv"))
        fields = [
            "timestamp", "symbol", "side",
            "entry_price", "exit_price",
            "qty_usd", "pnl_pct", "pnl_abs",
            "reason", "buy_score", "ai_score",
            "duration_minutes", "close_ts"
        ]
        safe_row = {k: row.get(k) for k in fields}
        cls._ensure_parent(path)
        with cls._lock:
            cls._ensure_header(path, fields)
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writerow(safe_row or {})


__all__ = ["CSVHandler"]
