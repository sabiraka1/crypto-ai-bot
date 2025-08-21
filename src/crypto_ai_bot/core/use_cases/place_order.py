## `place_order.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple
from ..events.bus import AsyncEventBus
from ..events import topics
from ..brokers.base import IBroker, OrderDTO
from ..storage.facade import Storage
from ...utils.ids import make_idempotency_key, make_client_order_id
from ...utils.metrics import inc
from ...utils.logging import get_logger
@dataclass(frozen=True)
class PlaceOrderResult:
    order: Optional[OrderDTO]
    client_order_id: str
    idempotency_key: str
    duplicate: bool
_log = get_logger("use_cases.place_order")
async def place_market_buy_quote(
    symbol: str,
    quote_amount: Decimal,
    *,
    exchange: str,
    storage: Storage,
    broker: IBroker,
    bus: Optional[AsyncEventBus],
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
) -> PlaceOrderResult:
    key = make_idempotency_key(symbol, "buy", idempotency_bucket_ms)
    client_oid = make_client_order_id(exchange, key)
    fresh = storage.idempotency.check_and_store(key, ttl_sec=idempotency_ttl_sec)
    if not fresh:
        row = storage.trades.find_by_client_order_id(client_oid)
        _log.info("duplicate_buy", extra={"symbol": symbol, "client_order_id": client_oid})
        inc("order_duplicate", {"side": "buy"})
        return PlaceOrderResult(order=None, client_order_id=client_oid, idempotency_key=key, duplicate=True)
    if bus:
        await bus.publish(
            topics.ORDER_SUBMITTED,
            {"symbol": symbol, "side": "buy", "client_order_id": client_oid, "quote_amount": str(quote_amount)},
            key=symbol,
        )
    order = await broker.create_market_buy_quote(symbol, quote_amount, client_order_id=client_oid)
    storage.trades.add_from_order(order)
    if bus:
        topic = topics.ORDER_EXECUTED if order.status == "closed" else topics.ORDER_FAILED
        await bus.publish(
            topic,
            {
                "symbol": symbol,
                "side": "buy",
                "client_order_id": client_oid,
                "status": order.status,
                "filled": str(order.filled),
                "price": str(order.price),
            },
            key=symbol,
        )
    inc("order_placed", {"side": "buy", "status": order.status})
    return PlaceOrderResult(order=order, client_order_id=client_oid, idempotency_key=key, duplicate=False)
async def place_market_sell_base(
    symbol: str,
    base_amount: Decimal,
    *,
    exchange: str,
    storage: Storage,
    broker: IBroker,
    bus: Optional[AsyncEventBus],
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
) -> PlaceOrderResult:
    key = make_idempotency_key(symbol, "sell", idempotency_bucket_ms)
    client_oid = make_client_order_id(exchange, key)
    fresh = storage.idempotency.check_and_store(key, ttl_sec=idempotency_ttl_sec)
    if not fresh:
        row = storage.trades.find_by_client_order_id(client_oid)
        _log.info("duplicate_sell", extra={"symbol": symbol, "client_order_id": client_oid})
        inc("order_duplicate", {"side": "sell"})
        return PlaceOrderResult(order=None, client_order_id=client_oid, idempotency_key=key, duplicate=True)
    if bus:
        await bus.publish(
            topics.ORDER_SUBMITTED,
            {"symbol": symbol, "side": "sell", "client_order_id": client_oid, "base_amount": str(base_amount)},
            key=symbol,
        )
    order = await broker.create_market_sell_base(symbol, base_amount, client_order_id=client_oid)
    storage.trades.add_from_order(order)
    if bus:
        topic = topics.ORDER_EXECUTED if order.status == "closed" else topics.ORDER_FAILED
        await bus.publish(
            topic,
            {
                "symbol": symbol,
                "side": "sell",
                "client_order_id": client_oid,
                "status": order.status,
                "filled": str(order.filled),
                "price": str(order.price),
            },
            key=symbol,
        )
    inc("order_placed", {"side": "sell", "status": order.status})
    return PlaceOrderResult(order=order, client_order_id=client_oid, idempotency_key=key, duplicate=False)