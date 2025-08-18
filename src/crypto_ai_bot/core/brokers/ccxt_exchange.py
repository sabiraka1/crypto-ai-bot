# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("brokers.ccxt_exchange")

try:
    import ccxt
except Exception:  # pragma: no cover
    ccxt = None


class CCXTExchange:
    """
    Тонкая обёртка над ccxt с «безопасной» сигнатурой create_order:
      create_order(symbol=..., type='market', side=..., amount=..., price=None, params={})
    Поддерживается и старое имя аргумента 'type_'.
    """

    def __init__(self, settings: Any, bus: Any = None, exchange_name: str | None = None):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")

        name = exchange_name or getattr(settings, "EXCHANGE", "binance")
        if not hasattr(ccxt, name):
            raise ValueError(f"Unknown ccxt exchange: {name}")

        klass = getattr(ccxt, name)
        # Инициализация с ключами (если заданы)
        self.ccxt = klass({
            "apiKey": getattr(settings, "API_KEY", None),
            "secret": getattr(settings, "API_SECRET", None),
            "enableRateLimit": True,
        })
        self.bus = bus
        # preload markets (нужно для precision/limits)
        try:
            self.ccxt.load_markets()
        except Exception as e:
            logger.warning("load_markets failed: %s", e)

    # --------- Market data ---------

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return self.ccxt.fetch_ticker(symbol)

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.ccxt.fetch_balance(params or {})

    # --------- Orders ---------

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
        Совместимо с вызовами:
          create_order(symbol=..., type='market', side='buy'|'sell', amount=..., price=None, params={})
        Поддержка старого имени аргумента: type_ (если передан и type пуст).
        """
        if not type and "type_" in kwargs:
            type = kwargs["type_"]
        return self.ccxt.create_order(symbol, type, side, amount, price, params or {})

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.ccxt.cancel_order(id, symbol, params or {})

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.ccxt.fetch_order(id, symbol, params or {})

    def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return self.ccxt.fetch_open_orders(symbol, since, limit, params or {})
