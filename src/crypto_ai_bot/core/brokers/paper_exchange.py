# src/crypto_ai_bot/core/brokers/paper_exchange.py
from __future__ import annotations
import time
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol
from crypto_ai_bot.utils import metrics


class PaperExchange(ExchangeInterface):
    """
    Упрощённый paper-режим.
    - fetch_ticker: возвращает синтетическую цену
    - fetch_ohlcv: генерирует синтетические свечи (линейный дрейф + слабый шум)
    - create_order: регистрирует ордер в памяти (мгновенно filled)
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._orders: List[Dict[str, Any]] = []
        self._bus = None  # опционально прокидывается фабрикой

    # --------- фабрика ----------
    @classmethod
    def from_settings(cls, cfg) -> "PaperExchange":
        """
        Унифицированная точка создания (требуется фабрикой create_broker()).
        Никаких внешних зависимостей: просто собираем инстанс.
        """
        return cls(cfg)

    # мягкая интеграция с event bus (если есть)
    def set_bus(self, bus) -> None:
        self._bus = bus

    # ---- helpers ----
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _synthetic_px(self) -> float:
        # синтетическая плавающая цена вокруг 100
        return 100.0 + (time.time() % 10)

    # ---- interface ----
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        exch_sym = to_exchange_symbol(symbol)
        px = self._synthetic_px()
        metrics.inc("broker_requests_total", {"exchange": "paper", "method": "fetch_ticker", "code": "200"})
        return {"symbol": exch_sym, "last": px, "timestamp": self._now_ms(), "bid": px * 0.999, "ask": px * 1.001}

    def fetch_order_book(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        """
        Небольшой синтетический стакан — пригодится для risk.check_spread().
        """
        px = self._synthetic_px()
        # возьмём узкий спред ~ 20 б.п. (по центру)
        bid = px * 0.999
        ask = px * 1.001
        bids = [[bid, 1.0]]
        asks = [[ask, 1.0]]
        return {"bids": bids, "asks": asks, "timestamp": self._now_ms()}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        to_exchange_symbol(symbol)  # нормализация для совместимости
        # простая генерация OHLCV (не для реальной торговли, но достаточно для теста пайплайна)
        now = self._now_ms()
        base = 100.0
        tf_ms = 60_000  # 1m как базовая; timeframe игнорируем
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
        # опционально отправим событие в шину (если есть)
        try:
            if self._bus:
                self._bus.publish({"type": "PaperOrderFilled", "order": order})
        except Exception:
            pass
        return order

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        # paper: считаем отменённым, если найден
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
