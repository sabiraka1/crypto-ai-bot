# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict, List, Optional
import time

from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol
from crypto_ai_bot.utils import metrics


class BacktestExchange(ExchangeInterface):
    """
    Простой backtest-адаптер.
    Если не передан источник OHLCV, отдаёт синтетические данные (как paper),
    чтобы не рушить пайплайн.
    """

    def __init__(self, cfg, ohlcv_source: Optional[List[List[float]]] = None) -> None:
        self.cfg = cfg
        self._ohlcv_source = ohlcv_source or []

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        exch_sym = to_exchange_symbol(symbol)
        px = 100.0 + (time.time() % 5)
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "fetch_ticker", "code": "200"})
        return {"symbol": exch_sym, "last": px, "timestamp": self._now_ms()}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        exch_sym = to_exchange_symbol(symbol)
        if self._ohlcv_source:
            data = self._ohlcv_source[-limit:]
        else:
            # синтетика если источник не передан
            now = self._now_ms()
            tf_ms = 60_000
            base = 100.0
            data = []
            for i in range(limit, 0, -1):
                t = now - i * tf_ms
                o = base + (i % 30) * 0.15
                h = o + 0.25
                l = o - 0.15
                c = o + 0.05
                v = 1.0
                data.append([t, o, h, l, c, v])
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "fetch_ohlcv", "code": "200"})
        return data

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        exch_sym = to_exchange_symbol(symbol)
        # в бэктесте обычно нет реального исполнения — возвращаем событийную заглушку
        oid = f"bt-{int(time.time()*1000)}"
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "create_order", "code": "200"})
        return {"id": oid, "symbol": exch_sym, "status": "accepted", "type": type_, "side": side, "amount": float(amount), "price": float(price) if price else None}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "cancel_order", "code": "200"})
        return {"id": order_id, "status": "canceled"}

    def fetch_balance(self) -> Dict[str, Any]:
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "fetch_balance", "code": "200"})
        return {"total": {"USDT": 1_000_000.0}}
