from __future__ import annotations

import time
from decimal import Decimal
from typing import Dict, Any

from .base import ExchangeInterface
# единый реестр преобразований
from . import to_exchange_symbol, normalize_symbol, normalize_timeframe
from crypto_ai_bot.utils.metrics import observe, inc


class PaperExchange(ExchangeInterface):
    """
    Простейший in-memory брокер для paper-режима.
    Нормализация символов/таймфреймов перед всеми операциями.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self._prices: Dict[str, Decimal] = {}
        self._balances = {"USDT": Decimal("100000.00")}

    # --- helpers
    def _now(self) -> float:
        return time.perf_counter()

    # --- интерфейс
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        t0 = self._now()
        symbol = normalize_symbol(symbol)
        timeframe = normalize_timeframe(timeframe)
        ex_symbol = to_exchange_symbol(symbol)

        # simple synthetic data
        base = float(self._prices.get(ex_symbol, Decimal("50000")))
        out = []
        ts = int(time.time()) - limit * 60
        for _ in range(limit):
            out.append([ts * 1000, base, base * 1.001, base * 0.999, base, 10.0])
            ts += 60
        observe("broker_latency_seconds", self._now() - t0, {"exchange": "paper", "method": "fetch_ohlcv"})
        return out

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        t0 = self._now()
        symbol = normalize_symbol(symbol)
        ex_symbol = to_exchange_symbol(symbol)
        price = self._prices.setdefault(ex_symbol, Decimal("50000"))
        observe("broker_latency_seconds", self._now() - t0, {"exchange": "paper", "method": "fetch_ticker"})
        return {"symbol": ex_symbol, "last": float(price)}

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None) -> Dict[str, Any]:
        t0 = self._now()
        symbol = normalize_symbol(symbol)
        ex_symbol = to_exchange_symbol(symbol)
        price = price or self._prices.setdefault(ex_symbol, Decimal("50000"))
        inc("broker_requests_total", {"exchange": "paper", "method": "create_order", "code": "200"})

        order = {
            "id": f"paper-{int(time.time()*1000)}",
            "symbol": ex_symbol,
            "side": side,
            "amount": str(amount),
            "price": str(price),
            "status": "filled",
            "ts": int(time.time() * 1000),
        }
        observe("broker_latency_seconds", self._now() - t0, {"exchange": "paper", "method": "create_order"})
        return order

    def fetch_balance(self) -> Dict[str, Any]:
        return {"free": dict(self._balances), "total": dict(self._balances)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return {"id": order_id, "status": "canceled"}
