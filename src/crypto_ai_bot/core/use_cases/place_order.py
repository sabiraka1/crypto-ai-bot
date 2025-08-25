from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from ..events.bus import AsyncEventBus
from ..brokers.base import IBroker, OrderDTO
from ..brokers.symbols import parse_symbol
from ..storage.facade import Storage
from ...utils.ids import make_idempotency_key, make_client_order_id
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ...utils.exceptions import ValidationError, TransientError, BrokerError


_log = get_logger("use_cases.place_order")


@dataclass(frozen=True)
class PlaceOrderResult:
    order: Optional[OrderDTO]
    client_order_id: str
    idempotency_key: str
    duplicate: bool


async def _emit(bus: AsyncEventBus, topic: str, payload: Dict[str, Any], *, key: str) -> None:
    try:
        await bus.publish(topic, payload, key=key)
    except Exception as exc:
        # события — «best effort»: не валим юзкейс из-за шины
        _log.error("event_publish_failed", extra={"topic": topic, "error": str(exc)})


def _reserve_idempotency(storage: Storage, key: str, *, ttl_sec: int) -> bool:
    """
    Резервирует идемпотентность. Возвращает True, если это первый вызов за окно TTL,
    и False, если ключ уже существует (дубликат).
    """
    try:
        return storage.idempotency.check_and_store(key, ttl_sec=ttl_sec)
    except Exception as exc:
        # Лучше «fail closed» (запретить), но для paper/тестов — «fail open» с логом:
        _log.error("idempotency_failed", extra={"key": key, "error": str(exc)})
        return True


async def place_market_buy_quote(
    symbol: str,
    quote_amount: Decimal,
    *,
    exchange: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
) -> PlaceOrderResult:
    """
    Покупка на фиксированную сумму quote (USDT и т.п.).
    Семантически однозначно: quote_amount — всегда валюта котировки.
    """
    pair = parse_symbol(symbol)
    key_bucket = (now_ms() // idempotency_bucket_ms) * idempotency_bucket_ms
    idem_key = make_idempotency_key(symbol, "buy", key_bucket)
    client_oid = make_client_order_id(exchange, idem_key)

    if not _reserve_idempotency(storage, idem_key, ttl_sec=idempotency_ttl_sec):
        _log.info("duplicate_buy", extra={"symbol": symbol, "client_order_id": client_oid})
        await _emit(bus, "order.duplicate", {"symbol": symbol, "side": "buy", "client_order_id": client_oid}, key=pair.as_pair)
        return PlaceOrderResult(order=None, client_order_id=client_oid, idempotency_key=idem_key, duplicate=True)

    try:
        # некоторые брокеры не принимают client_order_id — поддержим оба варианта
        try:
            order = await broker.create_market_buy_quote(symbol, quote_amount, client_order_id=client_oid)  # type: ignore[arg-type]
        except TypeError:
            order = await broker.create_market_buy_quote(symbol, quote_amount)  # type: ignore[misc]

        storage.audit.log("order_placed", {
            "symbol": symbol,
            "side": "buy",
            "quote_amount": str(quote_amount),
            "client_order_id": client_oid,
            "order_id": order.id,
            "status": order.status,
        })

        await _emit(bus, "order.executed", {
            "symbol": symbol,
            "side": "buy",
            "amount": str(order.amount),
            "filled": str(order.filled),
            "status": order.status,
            "client_order_id": order.client_order_id,
            "order_id": order.id,
        }, key=pair.as_pair)

        return PlaceOrderResult(order=order, client_order_id=client_oid, idempotency_key=idem_key, duplicate=False)

    except (ValidationError, BrokerError) as exc:
        _log.error("buy_failed", extra={"symbol": symbol, "error": str(exc)})
        await _emit(bus, "order.failed", {"symbol": symbol, "side": "buy", "error": str(exc)}, key=pair.as_pair)
        raise
    except TransientError as exc:
        _log.error("buy_transient_error", extra={"symbol": symbol, "error": str(exc)})
        await _emit(bus, "order.failed", {"symbol": symbol, "side": "buy", "error": "transient"}, key=pair.as_pair)
        raise
    except Exception as exc:
        _log.error("buy_unexpected_error", extra={"symbol": symbol, "error": str(exc)})
        await _emit(bus, "order.failed", {"symbol": symbol, "side": "buy", "error": "unexpected"}, key=pair.as_pair)
        raise


async def place_market_sell_base(
    symbol: str,
    base_amount: Decimal,
    *,
    exchange: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
) -> PlaceOrderResult:
    """
    Продажа фиксированного количества базовой валюты (например, 0.001 BTC).
    """
    pair = parse_symbol(symbol)
    key_bucket = (now_ms() // idempotency_bucket_ms) * idempotency_bucket_ms
    idem_key = make_idempotency_key(symbol, "sell", key_bucket)
    client_oid = make_client_order_id(exchange, idem_key)

    if not _reserve_idempotency(storage, idem_key, ttl_sec=idempotency_ttl_sec):
        _log.info("duplicate_sell", extra={"symbol": symbol, "client_order_id": client_oid})
        await _emit(bus, "order.duplicate", {"symbol": symbol, "side": "sell", "client_order_id": client_oid}, key=pair.as_pair)
        return PlaceOrderResult(order=None, client_order_id=client_oid, idempotency_key=idem_key, duplicate=True)

    try:
        try:
            order = await broker.create_market_sell_base(symbol, base_amount, client_order_id=client_oid)  # type: ignore[arg-type]
        except TypeError:
            order = await broker.create_market_sell_base(symbol, base_amount)  # type: ignore[misc]

        storage.audit.log("order_placed", {
            "symbol": symbol,
            "side": "sell",
            "base_amount": str(base_amount),
            "client_order_id": client_oid,
            "order_id": order.id,
            "status": order.status,
        })

        await _emit(bus, "order.executed", {
            "symbol": symbol,
            "side": "sell",
            "amount": str(order.amount),
            "filled": str(order.filled),
            "status": order.status,
            "client_order_id": order.client_order_id,
            "order_id": order.id,
        }, key=pair.as_pair)

        return PlaceOrderResult(order=order, client_order_id=client_oid, idempotency_key=idem_key, duplicate=False)

    except (ValidationError, BrokerError) as exc:
        _log.error("sell_failed", extra={"symbol": symbol, "error": str(exc)})
        await _emit(bus, "order.failed", {"symbol": symbol, "side": "sell", "error": str(exc)}, key=pair.as_pair)
        raise
    except TransientError as exc:
        _log.error("sell_transient_error", extra={"symbol": symbol, "error": str(exc)})
        await _emit(bus, "order.failed", {"symbol": symbol, "side": "sell", "error": "transient"}, key=pair.as_pair)
        raise
    except Exception as exc:
        _log.error("sell_unexpected_error", extra={"symbol": symbol, "error": str(exc)})
        await _emit(bus, "order.failed", {"symbol": symbol, "side": "sell", "error": "unexpected"}, key=pair.as_pair)
        raise
