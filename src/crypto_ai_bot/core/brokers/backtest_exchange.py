# src/crypto_ai_bot/core/brokers/backtest_exchange.py
"""
Единый бэктест-«брокер», совместимый по интерфейсу с CCXT-адаптером:
- fetch_ticker(symbol) -> {"last": price}
- create_order(symbol, type, side, amount) -> {"id": "...", "status": "closed", "filled": ...}
- fetch_order(id, symbol) -> {"status": "...", "filled": ..., "average": ...}

Заполняет рыночные ордера мгновенно по цене текущей свечи (close),
учитывая торговую комиссию (taker) и возвращая fee.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import itertools


@dataclass
class BacktestFees:
    taker_bps: float = 10.0  # 0.10%
    maker_bps: float = 10.0  # 0.10%


class BacktestExchange:
    def __init__(self, *, ohlcv: List[List[float]], symbol: str = "BTC/USDT", fees: Optional[BacktestFees] = None):
        """
        ohlcv: список списков [ts_ms, open, high, low, close, volume]
        """
        self.ohlcv = ohlcv
        self.symbol = symbol
        self.idx = 0
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._fees = fees or BacktestFees()
        self._id_iter = (f"bt-{i}" for i in itertools.count(1))

    # --- навигация по времени --- #
    def advance(self) -> bool:
        """Перейти к следующей свече. Возвращает False на конце."""
        if self.idx + 1 < len(self.ohlcv):
            self.idx += 1
            return True
        return False

    def current_price(self) -> float:
        return float(self.ohlcv[self.idx][4])  # close

    # --- CCXT-подобный интерфейс --- #
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        assert symbol == self.symbol, "single-symbol backtest exchange"
        return {"last": self.current_price(), "symbol": symbol}

    def create_order(self, *, symbol: str, type: str, side: str, amount: float) -> Dict[str, Any]:
        """
        Рыночный ордер: исполняется мгновенно по текущей цене.
        Возвращает CCXT-подобный объект.
        """
        assert symbol == self.symbol, "single-symbol backtest exchange"
        px = self.current_price()
        filled = float(amount)
        fee = px * filled * (self._fees.taker_bps / 10_000.0)
        oid = next(self._id_iter)
        order = {
            "id": oid,
            "symbol": symbol,
            "type": type,
            "side": side,
            "amount": amount,
            "price": px,
            "average": px,
            "filled": filled,
            "status": "closed",
            "fee": {"cost": fee, "currency": "USDT"},
        }
        self._orders[oid] = order
        return order

    def fetch_order(self, id: str, symbol: str) -> Dict[str, Any]:
        assert symbol == self.symbol
        return dict(self._orders.get(id, {"id": id, "symbol": symbol, "status": "closed", "filled": 0.0, "average": None}))
