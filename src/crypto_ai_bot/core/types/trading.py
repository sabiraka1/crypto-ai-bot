# src/crypto_ai_bot/core/types/trading.py
from __future__ import annotations
from typing import TypedDict, NotRequired


class Order(TypedDict, total=False):
    id: str
    symbol: str
    side: str        # "buy" | "sell"
    qty: str
    price: float
    status: str      # "executed" | "rejected" | "failed"
    reason: NotRequired[str]
