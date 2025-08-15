# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

@dataclass
class TradeStats:
    total_trades: int
    win_trades: int
    loss_trades: int
    total_pnl: float
    win_rate: float
    last_ts: int | None

class CSVHandler:
    @staticmethod
    def append_row(csv_path: str | Path, row: Mapping[str, Any]) -> None:
        p = Path(csv_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        exists = p.exists()
        with p.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not exists:
                w.writeheader()
            w.writerow(row)

    @staticmethod
    def get_trade_stats(csv_path: str | Path) -> TradeStats:
        p = Path(csv_path)
        if not p.exists():
            return TradeStats(0, 0, 0, 0.0, 0.0, None)

        total = wins = losses = 0
        pnl_sum = 0.0
        last_ts: int | None = None

        with p.open("r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            # Ğ¾Ğ¶Ğ¸Ğ´Ğ°ĞµĞ¼Ñ‹Ğµ Ğ¿Ğ¾Ğ»Ñ: ts, pnl
            for row in r:
                total += 1
                pnl = float(row.get("pnl", "0") or 0)
                pnl_sum += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                try:
                    ts = int(row.get("ts") or 0)
                    if ts:
                        last_ts = max(last_ts or 0, ts)
                except Exception:
                    pass

        win_rate = (wins / total) if total else 0.0
        return TradeStats(total, wins, losses, pnl_sum, win_rate, last_ts)

