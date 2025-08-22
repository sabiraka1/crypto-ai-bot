from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from ..events.bus import AsyncEventBus
from ..events import topics
from ..brokers.base import IBroker, OrderDTO
from ..storage.facade import Storage
from ...utils.ids import make_idempotency_key, make_client_order_id
from ...utils.metrics import inc, timer
from ...utils.logging import get_logger

# ValidationError как в settings.py
class ValidationError(ValueError):
    """Custom validation error for place_order"""
    pass


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
    # --- GUARDS ---
    if quote_amount is None or Decimal(quote_amount) <= 0:
        raise ValidationError("quote_amount must be > 0 for market BUY (quote).")
    
    # Простейшая защита от перепутанных юнитов
    MIN_QUOTE = Decimal("1")
    if Decimal(quote_amount) < MIN_QUOTE:
        raise ValidationError("Order quote amount is below safe minimum.")

    labels = {"symbol": symbol, "exchange": exchange, "side": "buy"}
    with timer("place_order_ms", labels, unit="ms"):
        key = make_idempotency_key(symbol, "buy", idempotency_bucket_ms)
        client_oid = make_client_order_id(exchange, key)

        fresh = storage.idempotency.check_and_store(key, ttl_sec=idempotency_ttl_sec)
        if not fresh:
            _ = storage.trades.find_by_client_order_id(client_oid)
            _log.info("duplicate_buy", extra={"symbol": symbol, "client_order_id": client_oid})
            # сохраняем старую метрику + добавляем агрегированную
            inc("order_duplicate", {"side": "buy"})
            inc("orders_duplicate_total", {"symbol": symbol, "side": "buy"})
            return PlaceOrderResult(order=None, client_order_id=client_oid, idempotency_key=key, duplicate=True)

        if bus:
            await bus.publish(
                topics.ORDER_SUBMITTED,
                {"symbol": symbol, "side": "buy", "client_order_id": client_oid, "quote_amount": str(quote_amount)},
                key=symbol,
            )

        with timer("broker_place_order_ms", labels, unit="ms"):
            order = await broker.create_market_buy_quote(symbol, quote_amount, client_order_id=client_oid)

        with timer("storage_write_ms", labels, unit="ms"):
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

            # сохраняем старую метрику + добавляем агрегированную
            inc("order_placed", {"side": "buy", "status": order.status})
            inc("orders_placed_total", {"symbol": symbol, "side": "buy", "status": order.status})
        
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
    # --- GUARDS ---
    if base_amount is None or Decimal(base_amount) <= 0:
        raise ValidationError("base_amount must be > 0 for market SELL (base).")

    labels = {"symbol": symbol, "exchange": exchange, "side": "sell"}
    with timer("place_order_ms", labels, unit="ms"):
        key = make_idempotency_key(symbol, "sell", idempotency_bucket_ms)
        client_oid = make_client_order_id(exchange, key)

        fresh = storage.idempotency.check_and_store(key, ttl_sec=idempotency_ttl_sec)
        if not fresh:
            _ = storage.trades.find_by_client_order_id(client_oid)
            _log.info("duplicate_sell", extra={"symbol": symbol, "client_order_id": client_oid})
            # сохраняем старую метрику + добавляем агрегированную
            inc("order_duplicate", {"side": "sell"})
            inc("orders_duplicate_total", {"symbol": symbol, "side": "sell"})
            return PlaceOrderResult(order=None, client_order_id=client_oid, idempotency_key=key, duplicate=True)

        if bus:
            await bus.publish(
                topics.ORDER_SUBMITTED,
                {"symbol": symbol, "side": "sell", "client_order_id": client_oid, "base_amount": str(base_amount)},
                key=symbol,
            )

        with timer("broker_place_order_ms", labels, unit="ms"):
            order = await broker.create_market_sell_base(symbol, base_amount, client_order_id=client_oid)

        with timer("storage_write_ms", labels, unit="ms"):
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

            # сохраняем старую метрику + добавляем агрегированную
            inc("order_placed", {"side": "sell", "status": order.status})
            inc("orders_placed_total", {"symbol": symbol, "side": "sell", "status": order.status})
        
    return PlaceOrderResult(order=order, client_order_id=client_oid, idempotency_key=key, duplicate=False)