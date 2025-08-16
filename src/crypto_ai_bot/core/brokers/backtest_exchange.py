from __future__ import annotations
from typing import Dict, Any, List, Optional
from decimal import Decimal

from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

class BacktestExchange(ExchangeInterface):
    def __init__(self, feed: Dict[str, Dict[str, List[List[float]]]] | None = None) -> None:
        self.feed = feed or {}

    @classmethod
    def from_settings(cls, cfg) -> "BacktestExchange":
        return cls(feed={})

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        sym = normalize_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        data = (((self.feed.get(sym) or {}).get(tf)) or [])
        if limit and limit > 0:
            return data[-limit:]
        return data

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        for tf in ("1m","5m","15m","1h","4h","1d"):
            arr = ((self.feed.get(sym) or {}).get(tf)) or []
            if arr:
                last = arr[-1]
                return {"symbol": sym, "last": float(last[4])}
        return {"symbol": sym, "last": 0.0}

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        return {
            "id": f"bt_{sym}_{side}_{amount}",
            "symbol": sym,
            "type": type_,
            "side": side,
            "amount": str(amount),
            "price": str(price) if price is not None else None,
            "status": "filled",
        }

    def fetch_balance(self) -> Dict[str, Any]:
        return {"total": {"USD": 100000.0}}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return {"id": order_id, "status": "canceled"}
