# src/crypto_ai_bot/trading/paper_store.py
from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict


class PaperStore:
    """
    Надёжное файловое хранилище для paper-режима.
    Сам создаёт директории и пустые файлы, чтобы не ловить PermissionError/FileNotFoundError.
    """

    def __init__(self, positions_path: str, orders_path: str, pnl_path: str):
        self.positions_path = positions_path
        self.orders_path = orders_path
        self.pnl_path = pnl_path
        self._ensure_files()

    # --- FS bootstrap ---------------------------------------------------------
    def _ensure_files(self) -> None:
        for p in (self.positions_path, self.orders_path, self.pnl_path):
            d = os.path.dirname(p)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)

        if not os.path.exists(self.positions_path):
            with open(self.positions_path, "w", encoding="utf-8") as f:
                json.dump({}, f)

        if not os.path.exists(self.orders_path):
            with open(self.orders_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["ts", "side", "amount", "price"])

        if not os.path.exists(self.pnl_path):
            with open(self.pnl_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["ts", "pnl"])

    # --- API ------------------------------------------------------------------
    def load_positions(self) -> Dict[str, Any]:
        with open(self.positions_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_positions(self, data: Dict[str, Any]) -> None:
        with open(self.positions_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def append_order(self, ts: int, side: str, amount: float, price: float) -> None:
        with open(self.orders_path, "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([ts, side, amount, price])

    def append_pnl(self, ts: int, pnl: float) -> None:
        with open(self.pnl_path, "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([ts, pnl])







