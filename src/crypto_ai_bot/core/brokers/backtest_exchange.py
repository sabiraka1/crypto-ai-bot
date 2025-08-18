# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations

import csv
import os
import time
from typing import Any, Dict, List, Optional


class _ClockShim:
    """Простой shim, чтобы time_sync и прочие места могли вызвать broker.ccxt.fetch_time()."""

    @staticmethod
    def fetch_time() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def milliseconds() -> int:
        return int(time.time() * 1000)


class BacktestExchange:
    """
    Лёгкий «бумажный» брокер для режима backtest.

    Совместимость с фабрикой: __init__(settings, bus=None, exchange_name: str|None=None)

    Источники цены (по приоритету):
      1) CSV (settings.BACKTEST_CSV_PATH) с колонками: time,open,high,low,close,volume
      2) Массив цен settings.BACKTEST_PRICES: List[float]
      3) Константа settings.BACKTEST_LAST_PRICE (по умолчанию 100.0)

    Поведение:
      - fetch_ticker(symbol) -> {"last": px, "close": px, "timestamp": ...}
      - create_order(...)    -> мгновенно "filled" по текущей цене; сдвигает курсор цены вперёд
      - остальные методы возвращают минимально достаточные структуры

    Примечания:
      - Имеет атрибуты `markets` (пустой словарь) и `ccxt` (ClockShim),
        чтобы не падали вызовы precision/limits и time_sync.
    """

    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None):
        self.settings = settings
        self.bus = bus
        self.exchange_name = exchange_name or "backtest"

        # shim'ы для совместимости
        self.ccxt = _ClockShim()
        self.markets: Dict[str, Dict[str, Any]] = {}  # precision/limits недоступны — пусть будет пусто

        # загрузка цен
        self._prices: List[float] = self._load_prices(settings)
        self._idx: int = 0
        self._orders: Dict[str, Dict[str, Any]] = {}

    # ------------- загрузка данных -------------
    def _load_prices(self, settings: Any) -> List[float]:
        # 1) CSV
        p = getattr(settings, "BACKTEST_CSV_PATH", None)
        if isinstance(p, str) and p and os.path.exists(p):
            out: List[float] = []
            try:
                with open(p, "r", newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        c = row.get("close")
                        if c is None:
                            continue
                        try:
                            out.append(float(c))
                        except Exception:
                            pass
                if out:
                    return out
            except Exception:
                pass

        # 2) Явный список цен
        arr = getattr(settings, "BACKTEST_PRICES", None)
        if isinstance(arr, list) and arr:
            try:
                return [float(x) for x in arr]
            except Exception:
                pass

        # 3) Константа
        return [float(getattr(settings, "BACKTEST_LAST_PRICE", 100.0))]

    # ------------- market data -------------
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
        return {
            "symbol": symbol,
            "last": px,
            "close": px,
            "timestamp": int(time.time() * 1000),
            "info": {"src": "backtest"},
        }

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # минимальный заглушечный баланс; многим участкам достаточно наличия метода
        return {"info": {"mode": "backtest"}}

    # ------------- orders -------------
    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Совместимо с вызовом из use_case:
          create_order(symbol=..., type='market', side='buy'|'sell', amount=..., price=None, params={})
        """
        ts = int(time.time() * 1000)
        px = self._cur_px()
        order_id = f"bt-{ts}-{len(self._orders) + 1}"
        od = {
            "id": order_id,
            "timestamp": ts,
            "status": "filled",
            "symbol": symbol,
            "side": side,
            "type": type,
            "price": float(px),
            "amount": float(amount),
        }
        self._orders[order_id] = od
        # имитируем движение по ряду
        self._advance()
        return od

    def cancel_order(
        self,
        id: str,
        symbol: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        od = self._orders.get(id)
        if not od:
            return {"id": id, "status": "canceled", "symbol": symbol}
        od["status"] = "canceled"
        return od

    def fetch_order(
        self,
        id: str,
        symbol: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._orders.get(id, {"id": id, "status": "closed", "symbol": symbol})

    def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        # исполняем мгновенно — «открытых» нет
        return []
