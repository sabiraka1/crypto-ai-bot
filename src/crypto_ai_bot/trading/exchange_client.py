# -*- coding: utf-8 -*-
"""
trading/exchange_client.py
--------------------------
Ğ•Ğ´Ğ¸Ğ½Ñ‹Ğ¹ Ğ°Ğ´Ğ°Ğ¿Ñ‚ĞµÑ€ Ğ´Ğ¾ÑÑ‚ÑƒĞ¿Ğ° Ğº Ğ±Ğ¸Ñ€Ğ¶Ğµ (Ñ‡ĞµÑ€ĞµĞ· ccxt).
ĞĞ¸ĞºĞ°ĞºĞ¸Ñ… Ğ¿Ñ€ÑĞ¼Ñ‹Ñ… `requests` Ğ¸ Ğ½Ğ¸ĞºĞ°ĞºĞ¾Ğ¹ Ğ»Ğ¾Ğ³Ğ¸ĞºĞ¸ Ğ¾Ğ±Ñ‰Ğ¸Ñ… HTTPâ€‘Ğ·Ğ°Ğ¿Ñ€Ğ¾ÑĞ¾Ğ² â€” Ñ‚Ğ¾Ğ»ÑŒĞºĞ¾ Ğ±Ğ¸Ñ€Ğ¶Ğ°.

Ğ˜ÑĞ¿Ğ¾Ğ»ÑŒĞ·Ğ¾Ğ²Ğ°Ğ½Ğ¸Ğµ:
    from crypto_ai_bot.trading.exchange_client import ExchangeClient
    ex = ExchangeClient.from_settings(Settings.build())
    ohlcv = ex.fetch_ohlcv('BTC/USDT', '15m', limit=500)

Ğ—Ğ°Ğ¼ĞµÑ‚ĞºĞ¸:
- Ğ¢Ğ°Ğ¹Ğ¼Ğ°ÑƒÑ‚Ñ‹/Ñ€ĞµÑ‚Ñ€Ğ°Ğ¸/Ğ¿Ñ€Ğ¾ĞºÑĞ¸ Ğ±ĞµÑ€ÑƒÑ‚ÑÑ Ğ¸Ğ· Settings (ĞµÑĞ»Ğ¸ Ğ·Ğ°Ğ´Ğ°Ğ½Ñ‹).
- Ğ’ĞºĞ»ÑÑ‡Ñ‘Ğ½ rateLimit ccxt (exchange.enableRateLimit = True).
- Ğ’ÑĞµ Ğ¼ĞµÑ‚Ğ¾Ğ´Ñ‹ Ğ¾Ğ±Ñ‘Ñ€Ğ½ÑƒÑ‚Ñ‹ Ğ² Ğ»Ğ¾Ğ²ÑƒÑˆĞºÑƒ Ğ¾ÑˆĞ¸Ğ±Ğ¾Ğº Ñ Ğ½Ğ¾Ñ€Ğ¼Ğ°Ğ»ÑŒĞ½Ñ‹Ğ¼Ğ¸ ÑĞ¾Ğ¾Ğ±Ñ‰ĞµĞ½Ğ¸ÑĞ¼Ğ¸.
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

    # --- Ñ„Ğ°Ğ±Ñ€Ğ¸ĞºĞ° Ğ¸Ğ· Settings ---
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

    # --- Ğ±Ğ°Ğ·Ğ¾Ğ²Ñ‹Ğµ Ğ¼ĞµÑ‚Ğ¾Ğ´Ñ‹ ---
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

    # --- ÑƒÑ‚Ğ¸Ğ»Ğ¸Ñ‚Ñ‹ ---
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


