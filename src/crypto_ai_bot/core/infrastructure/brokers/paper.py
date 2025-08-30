from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("broker.paper")


def _to_canonical(sym: str) -> str:
    """Локальная нормализация: 'btc_usdt' -> 'BTC/USDT', 'BTC/USDT' -> 'BTC/USDT'."""
    if "_" in sym and "/" not in sym:
        b, q = sym.split("_", 1)
        return f"{b.upper()}/{q.upper()}"
    return sym


@dataclass
class PaperBroker:
    """Простой симулятор рынка для тестов PAPER; не тянет application."""
    settings: Any

    async def fetch_ticker(self, symbol: str) -> dict:
        symbol = _to_canonical(symbol)
        px = dec(str(getattr(self.settings, "PAPER_PRICE", "60000") or "60000"))
        # разыгрываем +/- 0.05%
        delta = px * dec("0.0005")
        last = px + dec(str(random.uniform(float(-delta), float(delta))))
        spread = last * dec("0.0008")  # 8 bps
        bid = last - spread / 2
        ask = last + spread / 2
        return {"symbol": symbol, "last": last, "bid": bid, "ask": ask}

    async def fetch_balance(self, symbol: str) -> dict:
        symbol = _to_canonical(symbol)
        base, quote = symbol.split("/")
        free_base = dec(str(getattr(self.settings, "PAPER_FREE_BASE", "0") or "0"))
        free_quote = dec(str(getattr(self.settings, "PAPER_FREE_QUOTE", "100000") or "100000"))
        return {"free_base": free_base, "free_quote": free_quote}

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal,
                                      client_order_id: Optional[str] = None) -> Any:
        symbol = _to_canonical(symbol)
        t = await self.fetch_ticker(symbol)
        price = t["ask"]
        cost = quote_amount
        amount = dec("0")
        if price > 0 and cost > 0:
            amount = cost / price
        order = type("Order", (), {})()
        order.id = f"paper-{random.randrange(10**9)}"
        order.client_order_id = client_order_id
        order.symbol = symbol
        order.side = "buy"
        order.amount = amount
        order.filled = amount
        order.price = price
        order.cost = cost
        order.fee_quote = dec("0")
        order.ts_ms = 0
        return order

    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal,
                                      client_order_id: Optional[str] = None) -> Any:
        symbol = _to_canonical(symbol)
        t = await self.fetch_ticker(symbol)
        price = t["bid"]
        cost = base_amount * price
        order = type("Order", (), {})()
        order.id = f"paper-{random.randrange(10**9)}"
        order.client_order_id = client_order_id
        order.symbol = symbol
        order.side = "sell"
        order.amount = base_amount
        order.filled = base_amount
        order.price = price
        order.cost = cost
        order.fee_quote = dec("0")
        order.ts_ms = 0
        return order
