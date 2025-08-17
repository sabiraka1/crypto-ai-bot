# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations

import csv
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol


class BacktestExchange:
    """
    Простой CSV-реплей:
      - fetch_ohlcv читает последние N баров из CSV (ts,open,high,low,close,volume)
      - fetch_ticker возвращает last из последнего close
      - create_order эмулирует немедленный fill
    Ожидается путь к CSV: cfg.BACKTEST_CSV_PATH (по умолчанию data/backtest.csv)
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._cache: Dict[str, List[List[float]]] = {}

    @classmethod
    def from_settings(cls, cfg) -> "BacktestExchange":
        return cls(cfg)

    def _csv_path(self) -> str:
        return getattr(self.cfg, "BACKTEST_CSV_PATH", "data/backtest.csv")

    def _load_csv(self, path: str) -> List[List[float]]:
        rows: List[List[float]] = []
        if not os.path.exists(path):
            return rows
        with open(path, "r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            # ожидаем колонки: ts,open,high,low,close,volume
            for row in r:
                try:
                    rows.append([
                        float(row["ts"]),
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        float(row["volume"]),
                    ])
                except Exception:
                    continue
        return rows

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
        # timeframe игнорируем — CSV один, задача — отдать limit последних баров
        path = self._csv_path()
        key = f"{path}"
        if key not in self._cache:
            self._cache[key] = self._load_csv(path)
        data = self._cache[key]
        return data[-int(limit):] if limit else data

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        data = self.fetch_ohlcv(symbol, timeframe="1m", limit=1)
        last = float(data[-1][4]) if data else 0.0
        return {"symbol": symbol, "last": last}

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None) -> Dict[str, Any]:
        """
        Эмуляция моментального исполнения по цене last (или указанной price).
        """
        last = Decimal(str(self.fetch_ticker(symbol)["last"]))
        fill_price = price if (price and price > 0) else last
        return {
            "id": f"bt_{symbol}_{side}_{amount}",
            "symbol": symbol,
            "status": "filled",
            "filled": float(amount),
            "price": float(fill_price),
        }

    def fetch_balance(self) -> Dict[str, Any]:
        return {"free": {"USDT": 1_000_000}, "used": {}, "total": {"USDT": 1_000_000}}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return {"id": order_id, "status": "canceled"}
