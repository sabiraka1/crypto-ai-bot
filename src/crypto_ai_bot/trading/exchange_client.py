# -*- coding: utf-8 -*-
"""
trading/exchange_client.py
--------------------------
Единый адаптер доступа к бирже (через ccxt).
Никаких прямых `requests` и никакой логики общих HTTP‑запросов — только биржа.

Использование:
    from crypto_ai_bot.trading.exchange_client import ExchangeClient
    ex = ExchangeClient.from_settings(Settings.build())
    ohlcv = ex.fetch_ohlcv('BTC/USDT', '15m', limit=500)

Заметки:
- Таймауты/ретраи/прокси берутся из Settings (если заданы).
- Включён rateLimit ccxt (exchange.enableRateLimit = True).
- Все методы обёрнуты в ловушку ошибок с нормальными сообщениями.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.settings import Settings

try:
    import ccxt  # type: ignore
except Exception as e:  # pragma: no cover
    raise RuntimeError("ccxt is required for ExchangeClient. Install it via `pip install ccxt`. ") from e

logger = logging.getLogger(__name__)


class ExchangeClient:
    def __init__(self, exchange: Any, *, timeout: Optional[float] = None) -> None:
        self._ex = exchange
        self._timeout = timeout

    # --- фабрика из Settings ---
    @classmethod
    def from_settings(cls, cfg: Settings) -> "ExchangeClient":
        ex_id = getattr(cfg, "EXCHANGE_ID", "binance")
        api_key = getattr(cfg, "API_KEY", None)
        secret = getattr(cfg, "API_SECRET", None)
        password = getattr(cfg, "API_PASSWORD", None) or getattr(cfg, "API_PASSPHRASE", None)
        timeout = float(getattr(cfg, "HTTP_TIMEOUT", 8000)) * 1000 if float(getattr(cfg, "HTTP_TIMEOUT", 8.0)) < 1000 else float(getattr(cfg, "HTTP_TIMEOUT", 8000))

        if not hasattr(ccxt, ex_id):
            raise ValueError(f"Unknown exchange id in Settings.EXCHANGE_ID: {ex_id}")

        klass = getattr(ccxt, ex_id)
        exchange = klass({
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
            "timeout": int(timeout),  # ms
        })
        return cls(exchange, timeout=float(getattr(cfg, "HTTP_TIMEOUT", 8.0)))

    # --- базовые методы ---
    def fetch_ohlcv(self, symbol: str, timeframe: str, *, limit: int = 500) -> List[List[float]]:
        try:
            return self._ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            logger.exception("fetch_ohlcv failed: %r", e)
            raise

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            return self._ex.fetch_ticker(symbol)
        except Exception as e:
            logger.exception("fetch_ticker failed: %r", e)
            raise

    def create_order(self, symbol: str, type_: str, side: str, amount: float, price: float | None = None) -> Dict[str, Any]:
        try:
            if type_ == "market":
                return self._ex.create_order(symbol, type_, side, amount)
            return self._ex.create_order(symbol, type_, side, amount, price)
        except Exception as e:
            logger.exception("create_order failed: %r", e)
            raise

    def cancel_all_orders(self, symbol: str) -> Any:
        try:
            if hasattr(self._ex, "cancel_all_orders"):
                return self._ex.cancel_all_orders(symbol)
            # fallbacks
            open_orders = self._ex.fetch_open_orders(symbol)
            result = []
            for o in open_orders:
                try:
                    result.append(self._ex.cancel_order(o["id"], symbol))
                except Exception as _e:
                    logger.warning("cancel_order failed for %s: %r", o.get("id"), _e)
            return result
        except Exception as e:
            logger.exception("cancel_all_orders failed: %r", e)
            raise

    # --- утилиты ---
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            if hasattr(self._ex, "set_leverage"):
                self._ex.set_leverage(leverage, symbol)
                return True
            return False
        except Exception as e:
            logger.warning("set_leverage failed: %r", e)
            return False

    @property
    def raw(self) -> Any:
        return self._ex
