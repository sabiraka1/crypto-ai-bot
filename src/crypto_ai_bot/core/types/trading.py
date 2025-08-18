# src/crypto_ai_bot/core/types/trading.py
from __future__ import annotations
from typing import TypedDict, Optional

class OrderRequest(TypedDict, total=False):
    symbol: str
    side: str           # "buy" | "sell"
    qty: str            # Decimal as str
    type: str           # "market" | "limit"
    price: Optional[str]

class OrderResult(TypedDict, total=False):
    status: str         # "executed"|"skipped"|"duplicate"|"error"
    price: Optional[str]
    payload: dict

class PositionSnapshot(TypedDict, total=False):
    symbol: str
    qty: str
    avg_price: str
