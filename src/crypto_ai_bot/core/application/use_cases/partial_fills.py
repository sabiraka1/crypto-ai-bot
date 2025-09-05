from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application import events_topics as topics
from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

log = get_logger("use_cases.partial_fills")


@dataclass(frozen=True)
class FillDelta:
    client_order_id: str
    broker_order_id: str | None
    symbol: str
    side: str
    delta_base: Decimal  # сколько ДОзаполнилось с прошлого раза (>=0)
    now_filled: Decimal  # текущее filled


def _extract_ids(order: Mapping[str, Any]) -> tuple[str, str | None]:
    coid = str(order.get("clientOrderId") or order.get("client_order_id") or "")
    boid = order.get("id") or order.get("orderId") or order.get("broker_order_id")
    return coid, str(boid) if boid else None


def _calc_delta(order: Mapping[str, Any], prev_filled: Decimal | None) -> FillDelta | None:
    symbol = str(order.get("symbol") or "")
    side = str(order.get("side") or "").lower()
    now_filled = dec(order.get("filled"))
    if now_filled <= 0:
        return None

    coid, boid = _extract_ids(order)
    if not coid:
        log.warning("partial_fill_skip_no_client_id", extra={"order": order})
        return None

    delta = now_filled - dec(prev_filled or 0)
    if delta <= 0:
        return None

    return FillDelta(
        client_order_id=coid,
        broker_order_id=boid,
        symbol=symbol,
        side=side,
        delta_base=delta,
        now_filled=now_filled,
    )


async def _load_prev_filled(storage: StoragePort, client_order_id: str) -> Decimal | None:
    """
    Пытаемся узнать предыдущее filled:
      - если в репозитории ордеров есть метод get_filled(client_order_id) — используем его;
      - иначе, если есть trades.get_filled_sum(client_order_id) — используем сумму;
      - если нет API — возвращаем None (будет считаться, что дельта = now_filled).
    """
    try:
        orders_repo = getattr(storage, "orders", None)
        if orders_repo and hasattr(orders_repo, "get_filled"):
            return dec(await orders_repo.get_filled(client_order_id))  # type: ignore[no-any-return]

        trades_repo = getattr(storage, "trades", None)
        if trades_repo and hasattr(trades_repo, "get_filled_sum"):
            return dec(await trades_repo.get_filled_sum(client_order_id))  # type: ignore[no-any-return]
    except Exception:
        log.debug("load_prev_filled_failed", exc_info=True)
    return None


async def _persist_delta(storage: StoragePort, order: Mapping[str, Any], fd: FillDelta) -> None:
    """
    Сохраняем частичное исполнение:
      - если есть trades.record_partial_fill(...) — используем его;
      - иначе, если есть trades.add(...) — добавим унифицированную запись;
      - если ничего — просто залогируем (не падаем).
    """
    try:
        trades_repo = getattr(storage, "trades", None)
        if trades_repo and hasattr(trades_repo, "record_partial_fill"):
            await trades_repo.record_partial_fill(  # type: ignore[func-returns-value]
                client_order_id=fd.client_order_id,
                broker_order_id=fd.broker_order_id,
                symbol=fd.symbol,
                side=fd.side,
                delta_base=str(fd.delta_base),
                order_raw=dict(order),
            )
            return

        if trades_repo and hasattr(trades_repo, "add"):
            await trades_repo.add(  # type: ignore[func-returns-value]
                {
                    "client_order_id": fd.client_order_id,
                    "broker_order_id": fd.broker_order_id,
                    "symbol": fd.symbol,
                    "side": fd.side,
                    "filled_delta": str(fd.delta_base),
                    "order": dict(order),
                }
            )
            return

        log.warning("partial_fill_persist_no_repo", extra={"client_order_id": fd.client_order_id})
    except Exception:
        log.error("partial_fill_persist_failed", extra={"client_order_id": fd.client_order_id}, exc_info=True)


async def _publish_events(bus: EventBusPort | None, order: Mapping[str, Any], fd: FillDelta) -> None:
    if not bus:
        return
    try:
        await bus.publish(
            topics.TRADE_COMPLETED
            if fd.now_filled == dec(order.get("amount") or order.get("quantity") or 0)
            else topics.TRADE_SETTLED,
            {
                "client_order_id": fd.client_order_id,
                "broker_order_id": fd.broker_order_id,
                "symbol": fd.symbol,
                "side": fd.side,
                "delta_base": str(fd.delta_base),
                "now_filled": str(fd.now_filled),
                "raw": dict(order),
            },
        )
    except Exception:
        log.error("partial_fill_publish_failed", extra={"client_order_id": fd.client_order_id}, exc_info=True)


async def sync_partial_fills(
    *, symbol: str, broker: BrokerPort, storage: StoragePort, bus: EventBusPort | None
) -> dict[str, Any]:
    """
    Основной юзкейс: синхронизируем частичные/полные исполнения по открытому списку ордеров.
    Ничего не «ломаем», все несуществующие методы — опциональны.
    Возвращает агрегат по обработанным ордерам.
    """
    processed = 0
    created = 0
    completed = 0

    try:
        open_orders = await broker.fetch_open_orders(symbol)
    except Exception as exc:
        log.error("fetch_open_orders_failed", extra={"symbol": symbol, "error": str(exc)}, exc_info=True)
        return {"processed": 0, "created": 0, "completed": 0, "error": str(exc)}

    for order in open_orders or []:
        try:
            coid, _ = _extract_ids(order)
            if not coid:
                continue

            prev_filled = await _load_prev_filled(storage, coid)
            fd = _calc_delta(order, prev_filled)
            if not fd:
                continue

            await _persist_delta(storage, order, fd)
            await _publish_events(bus, order, fd)

            processed += 1
            created += 1
            if fd.now_filled == dec(order.get("amount") or order.get("quantity") or 0):
                completed += 1

        except Exception:
            log.error("partial_fill_process_failed", extra={"order": str(order)[:300]}, exc_info=True)

    return {"processed": processed, "created": created, "completed": completed}
