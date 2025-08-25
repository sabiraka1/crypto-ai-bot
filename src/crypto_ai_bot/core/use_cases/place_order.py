from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..brokers.base import IBroker, OrderDTO
from ..events.bus import AsyncEventBus
from ..events import topics
from ..storage.facade import Storage
from ...utils.ids import make_idempotency_key, make_client_order_id, short_hash
from ...utils.logging import get_logger
from ...utils.time import now_ms
from ...utils.exceptions import ValidationError, TransientError


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
    """
    BUY QUOTE c идемпотентностью и безопасной обработкой partial fills.
    Семантика: amount_quote — размер в КОТИРУЕМОЙ валюте (USDT).
    """
    # idem key по «ведру»
    idem_key = make_idempotency_key(symbol, "buy", idempotency_bucket_ms)
    client_id = make_client_order_id(exchange, f"{symbol}:buy:{short_hash(str(amount_quote))}")

    # атомарная регистрация (IdempotencyRepository.check_and_store)
    if not storage.idempotency.check_and_store(key=idem_key, ttl_sec=idempotency_ttl_sec):
        _log.info("duplicate_buy", extra={"symbol": symbol, "client_order_id": client_id})
        await bus.publish(topics.ORDER_EXECUTED, {"symbol": symbol, "side": "buy", "duplicate": True}, key=symbol)
        return PlaceOrderResult(order=None, client_order_id=client_id, idempotency_key=idem_key, duplicate=True)

    try:
        order = await broker.create_market_buy_quote(symbol, amount_quote=amount_quote)

        # Если частично исполнено — фиксируем факт, но не считаем ошибкой:
        partial = order.filled < order.amount or order.status != "closed"
        await bus.publish(
            topics.ORDER_EXECUTED,
            {
                "symbol": symbol,
                "side": "buy",
                "client_order_id": client_id,
                "order_id": order.id,
                "filled": order.filled,
                "amount": order.amount,
                "status": order.status,
                "partial": partial,
                "ts_ms": order.timestamp,
            },
            key=symbol,
        )

        # Аудит
        try:
            storage.audit.log(
                action="buy_market",
                payload={
                    "symbol": symbol,
                    "client_order_id": client_id,
                    "order_id": order.id,
                    "filled": order.filled,
                    "amount": order.amount,
                    "status": order.status,
                    "ts_ms": now_ms(),
                },
            )
        except Exception:
            pass

        return PlaceOrderResult(order=order, client_order_id=client_id, idempotency_key=idem_key, duplicate=False)

    except ValidationError:
        # постоянная ошибка — публикуем failed без ретраев
        await bus.publish(
            topics.ORDER_FAILED,
            {"symbol": symbol, "side": "buy", "client_order_id": client_id, "reason": "validation"},
            key=symbol,
        )
        raise
    except TransientError:
        # временная — можно настроить ретраи выше (retry decorator на use-case)
        await bus.publish(
            topics.ORDER_FAILED,
            {"symbol": symbol, "side": "buy", "client_order_id": client_id, "reason": "transient"},
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
    """
    SELL BASE c идемпотентностью и частичными исполнениями.
    Семантика: amount_base — количество БАЗОВОЙ валюты (BTC).
    """
    idem_key = make_idempotency_key(symbol, "sell", idempotency_bucket_ms)
    client_id = make_client_order_id(exchange, f"{symbol}:sell:{short_hash(str(amount_base))}")

    if not storage.idempotency.check_and_store(key=idem_key, ttl_sec=idempotency_ttl_sec):
        _log.info("duplicate_sell", extra={"symbol": symbol, "client_order_id": client_id})
        await bus.publish(topics.ORDER_EXECUTED, {"symbol": symbol, "side": "sell", "duplicate": True}, key=symbol)
        return PlaceOrderResult(order=None, client_order_id=client_id, idempotency_key=idem_key, duplicate=True)

    try:
        order = await broker.create_market_sell_base(symbol, amount_base=amount_base)
        partial = order.filled < order.amount or order.status != "closed"

        await bus.publish(
            topics.ORDER_EXECUTED,
            {
                "symbol": symbol,
                "side": "sell",
                "client_order_id": client_id,
                "order_id": order.id,
                "filled": order.filled,
                "amount": order.amount,
                "status": order.status,
                "partial": partial,
                "ts_ms": order.timestamp,
            },
            key=symbol,
        )

        try:
            storage.audit.log(
                action="sell_market",
                payload={
                    "symbol": symbol,
                    "client_order_id": client_id,
                    "order_id": order.id,
                    "filled": order.filled,
                    "amount": order.amount,
                    "status": order.status,
                    "ts_ms": now_ms(),
                },
            )
        except Exception:
            pass

        return PlaceOrderResult(order=order, client_order_id=client_id, idempotency_key=idem_key, duplicate=False)

    except ValidationError:
        await bus.publish(
            topics.ORDER_FAILED,
            {"symbol": symbol, "side": "sell", "client_order_id": client_id, "reason": "validation"},
            key=symbol,
        )
        raise
    except TransientError:
        await bus.publish(
            topics.ORDER_FAILED,
            {"symbol": symbol, "side": "sell", "client_order_id": client_id, "reason": "transient"},
            key=symbol,
        )
        raise