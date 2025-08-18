# src/crypto_ai_bot/core/types/events.py
from __future__ import annotations
from typing import TypedDict, NotRequired, Any, Dict


class BusEvent(TypedDict, total=False):
    type: str
    ts_ms: int
    symbol: str
    timeframe: str
    payload: NotRequired[Dict[str, Any]]
    error: NotRequired[str]


class DecisionEvaluatedEvent(BusEvent, total=False):
    type: str  # "DecisionEvaluated"
    decision: Dict[str, Any]


class OrderExecutedEvent(BusEvent, total=False):
    type: str  # "OrderExecuted"
    order_id: str
    side: str
    qty: str
    price: float
