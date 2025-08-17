# src/crypto_ai_bot/core/brokers/paper_exchange.py
from __future__ import annotations
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol
from crypto_ai_bot.utils import metrics


class PaperExchange(ExchangeInterface):
    """
    Упрощённый paper-режим.
    - fetch_ticker: возвращает синтетическую цену
    - fetch_ohlcv: генерирует синтетические свечи (линейный дрейф + шум ~ 0)
    - create_order: регистрирует ордер в памяти
    """
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._orders: List[Dict[str, Any]] = []

    # ---- helpers ----
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        exch_sym = to_exchange_symbol(symbol)
        # синтетическая цена вокруг 100
        px = 100.0 + (time.time() % 10)
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_ticker", "code": "200"})
        return {"symbol": exch_sym, "last": px, "timestamp": self._now_ms()}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        exch_sym = to_exchange_symbol(symbol)
        # простая генерация OHLCV (не для реальной торговли, но достаточная для теста пайплайна)
        now = self._now_ms()
        base = 100.0
        tf_ms = 60_000  # 1m как базовая; реально игнорируем timeframe
        out: List[List[float]] = []
        for i in range(limit, 0, -1):
            t = now - i * tf_ms
            o = base + (i % 50) * 0.1
            h = o + 0.2
            l = o - 0.2
            c = o + 0.05
            v = 1.0
            out.append([t, o, h, l, c, v])
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_ohlcv", "code": "200"})
        return out

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        exch_sym = to_exchange_symbol(symbol)
        oid = f"paper-{len(self._orders)+1}"
        order = {
            "id": oid,
            "symbol": exch_sym,
            "type": type_,
            "side": side,
            "amount": float(amount),
            "price": float(price) if price is not None else None,
            "timestamp": self._now_ms(),
            "status": "filled",  # paper → сразу filled
        }
        self._orders.append(order)
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "create_order", "code": "200"})
        return order

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        # paper: считаем отменённым если найден
        for o in self._orders:
            if o["id"] == order_id:
                o["status"] = "canceled"
                break
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "cancel_order", "code": "200"})
        return {"id": order_id, "status": "canceled"}

    def fetch_balance(self) -> Dict[str, Any]:
        # фиктивный баланс
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_balance", "code": "200"})
        return {"total": {"USDT": 10_000.0}}
