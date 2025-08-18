# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations
import csv, time, os
from typing import Any, Dict, List, Optional

class BacktestExchange:
    """
    Совместимый с фабрикой бэктест-«брокер».
    Источник цены:
      1) CSV из settings.BACKTEST_CSV_PATH с колонками time,open,high,low,close,volume (unix_ms или iso8601 не требуется — берём 'close')
      2) settings.BACKTEST_PRICES: List[float]
      3) fallback: settings.BACKTEST_LAST_PRICE или 100.0

    Ордеры исполняются мгновенно по текущей last. Этого достаточно для smoke/e2e и простых стратегий.
    """
    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None):
        self.settings = settings
        self.bus = bus
        self.exchange_name = exchange_name or "backtest"

        self._prices: List[float] = []
        self._idx = 0
        # попытка загрузить CSV
        p = getattr(settings, "BACKTEST_CSV_PATH", None)
        if isinstance(p, str) and p and os.path.exists(p):
            try:
                with open(p, "r", newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        close = row.get("close")
                        if close is None: continue
                        try:
                            self._prices.append(float(close))
                        except Exception:
                            pass
            except Exception:
                self._prices = []
        # список цен из конфига
        if not self._prices:
            arr = getattr(settings, "BACKTEST_PRICES", None)
            if isinstance(arr, list) and arr:
                try:
                    self._prices = [float(x) for x in arr]
                except Exception:
                    self._prices = []
        # fallback одна цена
        if not self._prices:
            self._prices = [float(getattr(settings, "BACKTEST_LAST_PRICE", 100.0))]

        self._orders: Dict[str, Dict[str, Any]] = {}

    # --------- market data ---------
    def _cur_px(self) -> float:
        if not self._prices:
            return 100.0
        i = min(max(0, self._idx), len(self._prices) - 1)
        return float(self._prices[i])

    def _advance(self) -> None:
        if self._idx < len(self._prices) - 1:
            self._idx += 1

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        px = self._cur_px()
        return {"symbol": symbol, "last": px, "close": px, "timestamp": int(time.time() * 1000), "info": {"src": "bt"}}

    # --------- trading ---------
    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ts = int(time.time() * 1000)
        px = self._cur_px()
        order_id = f"bt-{ts}-{len(self._orders)+1}"
        # мгновенно исполняем
        od = {"id": order_id, "timestamp": ts, "status": "filled", "symbol": symbol, "side": side, "type": type,
              "price": float(px), "amount": float(amount)}
        self._orders[order_id] = od
        # двигаем «время» вперёд (если есть цены)
        self._advance()
        return od

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        od = self._orders.get(id)
        if not od:
            return {"id": id, "status": "canceled", "symbol": symbol}
        od["status"] = "canceled"
        return od

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._orders.get(id, {"id": id, "status": "closed", "symbol": symbol})

    def fetch_open_orders(self, symbol: Optional[str] = None, since: Optional[int] = None,
                          limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # всё исполняется мгновенно → открытых нет
        return []

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"info": {"mode": "backtest"}}
