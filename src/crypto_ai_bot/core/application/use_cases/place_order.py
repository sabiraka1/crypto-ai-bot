from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, OrderDTO
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events import topics
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.exceptions import ValidationError, TransientError

_log = get_logger("use_cases.place_order")

@dataclass(frozen=True)
class PlaceOrderResult:
    order: Optional[OrderDTO]
    client_order_id: str
    idempotency_key: str
    duplicate: bool = False

async def place_market_buy_quote(
    symbol: str,
    amount_quote: Decimal,
    *,
    exchange: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
) -> PlaceOrderResult:
    bucket = (now_ms() // idempotency_bucket_ms) * idempotency_bucket_ms
    idem_key = f"{symbol}:buy:{bucket}"
    client_id = make_client_order_id(exchange, f"{symbol}:buy")

    if not storage.idempotency.check_and_store(key=idem_key, ttl_sec=idempotency_ttl_sec, default_bucket_ms=idempotency_bucket_ms):
        _log.info("duplicate_buy", extra={"symbol": symbol, "client_order_id": client_id})
        await bus.publish(topics.ORDER_EXECUTED, {"symbol": symbol, "side": "buy", "duplicate": True}, key=symbol)
        return PlaceOrderResult(order=None, client_order_id=client_id, idempotency_key=idem_key, duplicate=True)

    try:
        order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=amount_quote, client_order_id=client_id)
        partial = order.filled < order.amount or order.status != "closed"
        
        await bus.publish(
            topics.ORDER_EXECUTED,
            {
                "symbol": symbol,
                "side": "buy",
                "client_order_id": client_id,
                "order_id": order.id,
                "filled": str(order.filled),
                "amount": str(order.amount),
                "status": order.status,
                "partial": partial,
                "ts_ms": order.timestamp,
            },
            key=symbol,
        )
        
        try:
            storage.trades.add_from_order(order)
            storage.audit.add(
                action="buy_market",
                payload={"symbol": symbol, "order_id": order.id, "amount": str(order.amount)},
                ts_ms=now_ms(),
            )
        except Exception:
            pass

        return PlaceOrderResult(order=order, client_order_id=client_id, idempotency_key=idem_key, duplicate=False)

    except (ValidationError, TransientError) as exc:
        await bus.publish(
            topics.ORDER_FAILED,
            {"symbol": symbol, "side": "buy", "client_order_id": client_id, "reason": str(exc)},
            key=symbol,
        )
        raise

async def place_market_sell_base(
    symbol: str,
    amount_base: Decimal,
    *,
    exchange: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
) -> PlaceOrderResult:
    bucket = (now_ms() // idempotency_bucket_ms) * idempotency_bucket_ms
    idem_key = f"{symbol}:sell:{bucket}"
    client_id = make_client_order_id(exchange, f"{symbol}:sell")

    if not storage.idempotency.check_and_store(key=idem_key, ttl_sec=idempotency_ttl_sec, default_bucket_ms=idempotency_bucket_ms):
        _log.info("duplicate_sell", extra={"symbol": symbol, "client_order_id": client_id})
        await bus.publish(topics.ORDER_EXECUTED, {"symbol": symbol, "side": "sell", "duplicate": True}, key=symbol)
        return PlaceOrderResult(order=None, client_order_id=client_id, idempotency_key=idem_key, duplicate=True)

    try:
        order = await broker.create_market_sell_base(symbol=symbol, base_amount=amount_base, client_order_id=client_id)
        partial = order.filled < order.amount or order.status != "closed"

        await bus.publish(
            topics.ORDER_EXECUTED,
            {
                "symbol": symbol,
                "side": "sell",
                "client_order_id": client_id,
                "order_id": order.id,
                "filled": str(order.filled),
                "amount": str(order.amount),
                "status": order.status,
                "partial": partial,
                "ts_ms": order.timestamp,
            },
            key=symbol,
        )

        try:
            storage.trades.add_from_order(order)
            storage.audit.add(
                action="sell_market",
                payload={"symbol": symbol, "order_id": order.id, "amount": str(order.amount)},
                ts_ms=now_ms(),
            )
        except Exception:
            pass

        return PlaceOrderResult(order=order, client_order_id=client_id, idempotency_key=idem_key, duplicate=False)

    except (ValidationError, TransientError) as exc:
        await bus.publish(
            topics.ORDER_FAILED,
            {"symbol": symbol, "side": "sell", "client_order_id": client_id, "reason": str(exc)},
            key=symbol,
        )
        raise