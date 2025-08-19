# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import csv

class BacktestExchange:
    """
    Простая backtest-реализация под ExchangeInterface.
    Источник цены:
      - settings.BACKTEST_PRICES: list[float] (опционально)
      - или settings.BACKTEST_CSV_PATH: CSV с колонкой 'close' (или первой числовой)
      - fallback: settings.BACKTEST_LAST_PRICE (float)
    Ордеры исполняются по текущей last (market).
    """

    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None) -> None:
        self.settings = settings
        self.bus = bus
        self.exchange_name = exchange_name or "backtest"
        self._i = 0
        self._prices: List[float] = []

        prices = getattr(settings, "BACKTEST_PRICES", None)
        if isinstance(prices, list) and prices:
            self._prices = [float(x) for x in prices if x is not None]
        elif getattr(settings, "BACKTEST_CSV_PATH", None):
            self._prices = self._load_csv(getattr(settings, "BACKTEST_CSV_PATH"))
        if not self._prices:
            self._prices = [float(getattr(settings, "BACKTEST_LAST_PRICE", 100.0))]

    def _load_csv(self, path: str) -> List[float]:
        out: List[float] = []
        with open(path, "r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            if "close" in r.fieldnames:
                for row in r:
                    try:
                        out.append(float(row["close"]))
                    except Exception:
                        pass
            else:
                f.seek(0)
                rr = csv.reader(f)
                for row in rr:
                    try:
                        out.append(float(row[0]))
                    except Exception:
                        pass
        return out or [float(getattr(self.settings, "BACKTEST_LAST_PRICE", 100.0))]

    # --- market data ---
    def _cur(self) -> float:
        if self._i >= len(self._prices):
            self._i = len(self._prices) - 1
        if self._i < 0:
            self._i = 0
        return float(self._prices[self._i])

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return {"symbol": symbol, "last": self._cur(), "close": self._cur()}

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # для smoke тестов: фиктивный баланс
        return {"free": {"USDT": 1_000_000.0}, "total": {"USDT": 1_000_000.0}}

    # --- orders ---
    def create_order(
        self, symbol: str, type: str, side: str, amount: float,
        price: Optional[float] = None, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Dict[str, Any]:
        last = self._cur()
        px = last if type == "market" or price is None else float(price)
        return {
            "id": f"bt-{self._i}",
            "symbol": symbol,
            "side": side,
            "type": type,
            "price": float(px),
            "amount": float(amount),
            "status": "closed",
        }

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"id": id, "canceled": True}

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"id": id, "status": "closed"}

    def fetch_open_orders(
        self, symbol: Optional[str] = None, since: Optional[int] = None,
        limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        return []
