# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils import metrics

log = get_logger(__name__)


def _load_csv(path: str) -> List[List[float]]:
    """Ожидается CSV с колонками: ts,open,high,low,close,volume."""
    rows: List[List[float]] = []
    if not path or not os.path.exists(path):
        return rows
    try:
        with open(path, "r", encoding="utf-8") as f:
            r = csv.reader(f)
            header = next(r, None)
            for line in r:
                if not line:
                    continue
                try:
                    ts = float(line[0]); o = float(line[1]); h = float(line[2]); l = float(line[3]); c = float(line[4])
                    v = float(line[5]) if len(line) > 5 else 0.0
                    rows.append([ts, o, h, l, c, v])
                except Exception:
                    continue
    except Exception as e:
        log.warning("Backtest CSV load failed: %s: %s", type(e).__name__, e)
    return rows


@dataclass
class BacktestExchange:
    """Простой backtest-брокер для оффлайн-данных."""
    symbol: str
    timeframe: str
    ohlcv: List[List[float]]
    bus: Optional[Any] = None

    @classmethod
    def from_settings(cls, cfg: Any, *, bus: Optional[Any] = None) -> "BacktestExchange":
        path = getattr(cfg, "BACKTEST_CSV_PATH", "data/backtest.csv")
        sym = getattr(cfg, "SYMBOL", "BTC/USDT")
        tf = getattr(cfg, "TIMEFRAME", "1h")
        data = _load_csv(path)
        if not data:
            log.warning("BacktestExchange: CSV '%s' is empty or missing; using synthetic flat price", path)
            data = [[0, 0, 0, 0, 10_000.0, 0.0]]
        return cls(symbol=sym, timeframe=tf, ohlcv=data, bus=bus)

    # -------- Market data --------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
        if symbol != self.symbol:
            # для простоты отдаём ту же серию — нормализация вне брокера
            pass
        limit = max(1, int(limit))
        return self.ohlcv[-limit:] if len(self.ohlcv) >= limit else self.ohlcv[:]

    def fetch_ticker(self, symbol: str) -> Dict[str, float]:
        series = self.ohlcv[-1] if self.ohlcv else [0, 0, 0, 0, 0, 0]
        last = float(series[4]) if len(series) >= 5 else 0.0
        return {"last": last, "bid": last * 0.999, "ask": last * 1.001}

    def fetch_order_book(self, symbol: str) -> Dict[str, Any]:
        t = self.fetch_ticker(symbol)
        bid = float(t.get("bid") or 0.0)
        ask = float(t.get("ask") or 0.0)
        return {"bids": [[bid, 1.0]], "asks": [[ask, 1.0]]}

    # -------- Trading (synchronous fill) --------
    def _safe_publish(self, ev: Dict[str, Any]) -> None:
        b = self.bus
        if not b:
            return
        try:
            b.publish(ev)
        except Exception as e:
            # не падаем, но логируем и считаем
            try:
                metrics.inc("bus_publish_errors_total", {"exchange": "backtest", "type": str(ev.get("type"))})
            except Exception:
                pass
            log.warning("BacktestExchange: bus.publish failed: %s: %s", type(e).__name__, e)

    def place_order(self, *, symbol: str, side: str, amount: float) -> Dict[str, Any]:
        """Имитация моментального исполнения рыночного ордера."""
        t = self.fetch_ticker(symbol)
        px = float(t.get("last") or 0.0)
        order = {
            "id": f"bt-{len(self.ohlcv)}",
            "status": "executed",
            "symbol": symbol,
            "side": side,
            "amount": float(amount),
            "price": px,
        }
        # событие в шину
        self._safe_publish({
            "type": "OrderExecuted",
            "symbol": symbol,
            "side": side,
            "amount": float(amount),
            "price": px,
        })
        return order

    # часто в use_case вызывают create_order(...)/submit_order(...)
    def create_order(self, symbol: str, side: str, amount: float, order_type: str = "market") -> Dict[str, Any]:
        return self.place_order(symbol=symbol, side=side, amount=amount)

    def submit_order(self, symbol: str, side: str, amount: float, order_type: str = "market") -> Dict[str, Any]:
        return self.place_order(symbol=symbol, side=side, amount=amount)
