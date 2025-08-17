# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict, List, Optional
import time
import os

from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol
from crypto_ai_bot.utils import metrics

try:
    from crypto_ai_bot.io.csv_handler import read_ohlcv_csv  # опционально
except Exception:
    read_ohlcv_csv = None  # type: ignore


class BacktestExchange(ExchangeInterface):
    """
    Простой backtest-адаптер.
    Если не передан источник OHLCV, отдаёт синтетические данные (как paper),
    чтобы не рушить пайплайн.
    """

    def __init__(self, cfg, ohlcv_source: Optional[List[List[float]]] = None) -> None:
        self.cfg = cfg
        self._ohlcv_source = ohlcv_source or []
        self._bus = None

    # --------- фабрика ----------
    @classmethod
    def from_settings(cls, cfg) -> "BacktestExchange":
        """
        Унифицированная точка создания (требуется фабрикой create_broker()).
        Пытаемся подхватить CSV, если он указан и доступен; иначе работаем на синтетике.
        """
        source: Optional[List[List[float]]] = None
        path = getattr(cfg, "BACKTEST_CSV_PATH", None)
        if path and isinstance(path, str) and os.path.exists(path) and read_ohlcv_csv:
            try:
                rows = read_ohlcv_csv(path)
                # конвертируем в массивы [ts,o,h,l,c,v]
                source = [[r["ts_ms"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in rows]
            except Exception:
                source = None
        return cls(cfg, ohlcv_source=source)

    def set_bus(self, bus) -> None:
        self._bus = bus

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        exch_sym = to_exchange_symbol(symbol)
        px = 100.0 + (time.time() % 5)
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "fetch_ticker", "code": "200"})
        return {"symbol": exch_sym, "last": px, "timestamp": self._now_ms(), "bid": px * 0.999, "ask": px * 1.001}

    def fetch_order_book(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        px = 100.0 + (time.time() % 5)
        return {"bids": [[px * 0.999, 1.0]], "asks": [[px * 1.001, 1.0]], "timestamp": self._now_ms()}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        to_exchange_symbol(symbol)
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
        order = {"id": oid, "symbol": exch_sym, "status": "accepted", "type": type_, "side": side, "amount": float(amount), "price": float(price) if price else None}
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "create_order", "code": "200"})
        try:
            if self._bus:
                self._bus.publish({"type": "BacktestOrderAccepted", "order": order})
        except Exception:
            pass
        return order

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "cancel_order", "code": "200"})
        return {"id": order_id, "status": "canceled"}

    def fetch_balance(self) -> Dict[str, Any]:
        metrics.inc("broker_requests_total", {"exchange": "backtest", "method": "fetch_balance", "code": "200"})
        return {"total": {"USDT": 1_000_000.0}}
