from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from crypto_ai_bot.core.application import events_topics as EVT
from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, OrderLike
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.partial_fills")


def _dec(x: Any, default: str = "0") -> Decimal:
    try:
        return dec(str(x if x is not None else default))
    except Exception:
        return dec(default)


def _ratio(filled: Decimal, amount: Decimal) -> Decimal:
    if amount <= 0:
        return dec("1")
    return (filled / amount).quantize(dec("0.00000001"))


def _is_closed(status: str | None) -> bool:
    s = (status or "").lower()
    return s in ("closed", "filled", "canceled", "rejected")


def _is_open(status: str | None) -> bool:
    s = (status or "").lower()
    return s in ("open", "partially_filled", "partial", "new", "pending")


@dataclass
class PartialFillHandler:
    bus: EventBusPort

    async def handle(self, order: OrderLike, broker: BrokerPort, client_order_id: str) -> OrderLike | None:
        """
        If partially filled < 95% - fill remainder at market.
        For buy amount treat as quote, for sell - as base (as in current model).
        """
        try:
            filled = _dec(getattr(order, "filled", 0))
            amount = _dec(getattr(order, "amount", 0))
            if amount <= 0:
                return None

            ratio = _ratio(filled, amount)
            if ratio >= dec("0.95"):
                return None

            remaining = amount - filled
            if remaining <= 0:
                return None

            symbol = getattr(order, "symbol", "") or ""
            if not symbol:
                return None

            side = (getattr(order, "side", "") or "").lower()

            # Prevent cycling - create follow-up only once
            if client_order_id and client_order_id.endswith("-pf"):
                return None

            if side == "buy":
                follow = await broker.create_market_buy_quote(
                    symbol=symbol,
                    quote_amount=remaining,  # модель: buy-amount трактуем как quote
                    client_order_id=f"{client_order_id}-pf" if client_order_id else None,
                )
            else:
                follow = await broker.create_market_sell_base(
                    symbol=symbol,
                    base_amount=remaining,
                    client_order_id=f"{client_order_id}-pf" if client_order_id else None,
                )

            await self.bus.publish(
                EVT.TRADE_PARTIAL_FOLLOWUP,
                {
                    "parent_client_order_id": client_order_id,
                    "follow_client_order_id": getattr(follow, "client_order_id", ""),
                    "symbol": symbol,
                    "side": side,
                    "remaining": str(remaining),
                },
            )
            inc("partial_followup_total", symbol=symbol, side=side)
            return cast(OrderLike, follow)
        except Exception as exc:
            _log.error("partial_followup_failed", extra={"error": str(exc)}, exc_info=True)
            inc("partial_followup_errors_total")
            return None


async def _process_single_order(
    row: dict,
    broker: BrokerPort,
    storage: Any,
    bus: EventBusPort,
    pfh: PartialFillHandler,
    symbol: str,
    timeout_sec: int,
    min_ratio_for_ok: Decimal,
) -> None:
    """Process a single order (helper to reduce complexity)."""
    if not isinstance(row, dict):
        return

    broker_order_id = row.get("broker_order_id", "") or ""
    client_order_id = row.get("client_order_id", "") or ""
    side = (row.get("side") or "").lower()
    ts_ms = int(row.get("ts_ms") or 0)

    # Calculate age
    age_sec = 0
    try:
        import time

        age_sec = max(0, int(time.time()) - ts_ms // 1000) if ts_ms else 0
    except Exception:
        pass

    # 1) Fetch actual status from exchange
    fetched: OrderLike | None = None
    try:
        if broker_order_id:
            # Важно: совместимо с CcxtBroker(fetch_order(*, symbol, broker_order_id))
            fetched = await broker.fetch_order(symbol=symbol, broker_order_id=broker_order_id)
        elif client_order_id and hasattr(broker, "fetch_order_by_client_id"):
            fetched = await broker.fetch_order_by_client_id(client_order_id, symbol)  # type: ignore[attr-defined]
        else:
            _log.warning("fetch_order_skipped_no_ids", extra={"symbol": symbol})
            return
    except Exception:
        _log.error(
            "fetch_order_failed",
            extra={"symbol": symbol, "broker_order_id": broker_order_id},
            exc_info=True,
        )
        inc("settle_fetch_order_errors_total", symbol=symbol)
        return

    if not fetched:
        _log.warning("fetch_order_empty", extra={"symbol": symbol, "broker_order_id": broker_order_id})
        return

    # 2) Synchronize progress (filled) and status
    filled = _dec(getattr(fetched, "filled", row.get("filled", "0")))
    amount = _dec(getattr(fetched, "amount", row.get("amount", "0")))
    status = getattr(fetched, "status", row.get("status", "open"))
    ratio = _ratio(filled, amount)

    # Write progress filled (not closing)
    try:
        if broker_order_id and _is_open(status) and hasattr(storage, "orders"):
            storage.orders.update_progress(broker_order_id, str(filled))
    except Exception:
        _log.error(
            "update_progress_failed",
            extra={"symbol": symbol, "broker_order_id": broker_order_id},
            exc_info=True,
        )

    # 3) If order closed - record and publish event
    if _is_closed(status):
        try:
            if broker_order_id and hasattr(storage, "orders"):
                storage.orders.mark_closed(broker_order_id, str(filled))
        except Exception:
            _log.error(
                "mark_closed_failed",
                extra={"symbol": symbol, "broker_order_id": broker_order_id},
                exc_info=True,
            )

        # best-effort: record trade (if not already recorded)
        try:
            if hasattr(storage, "trades") and hasattr(storage.trades, "add_from_order"):
                storage.trades.add_from_order(fetched)
        except Exception:
            _log.error("add_trade_failed", extra={"symbol": symbol}, exc_info=True)

        # settled event
        try:
            await bus.publish(
                EVT.TRADE_SETTLED,
                {
                    "symbol": symbol,
                    "side": side,
                    "order_id": getattr(fetched, "id", "") or getattr(fetched, "order_id", ""),
                    "client_order_id": getattr(fetched, "client_order_id", client_order_id),
                    "filled": str(filled),
                    "amount": str(amount),
                    "ratio": str(ratio),
                    "status": status,
                },
            )
            inc("trade_settled_total", symbol=symbol, side=side)
        except Exception:
            _log.error("publish_trade_settled_failed", extra={"symbol": symbol}, exc_info=True)
        return

    # 4) If order hung too long - send timeout (not closing)
    if age_sec > timeout_sec and ratio < min_ratio_for_ok:
        try:
            await bus.publish(
                EVT.TRADE_SETTLEMENT_TIMEOUT,
                {
                    "symbol": symbol,
                    "side": side,
                    "order_id": getattr(fetched, "id", "") or broker_order_id,
                    "client_order_id": getattr(fetched, "client_order_id", client_order_id),
                    "filled": str(filled),
                    "amount": str(amount),
                    "ratio": str(ratio),
                    "age_sec": age_sec,
                },
            )
            inc("trade_settlement_timeout_total", symbol=symbol, side=side)
        except Exception:
            _log.error("publish_trade_settlement_timeout_failed", extra={"symbol": symbol}, exc_info=True)

    # 5) If partially filled - try to fill remainder at market
    try:
        if ratio > dec("0") and ratio < dec("0.95"):
            await pfh.handle(cast(OrderLike, fetched), broker, client_order_id)
    except Exception:
        _log.error("partial_followup_call_failed", extra={"symbol": symbol}, exc_info=True)


async def settle_orders(
    symbol: str,
    storage: Any,
    broker: BrokerPort,
    bus: EventBusPort,
    settings: Any,
) -> None:
    """
    Iterate through open orders by symbol, fetch actual status from exchange,
    update local state, handle follow-up on partial fills,
    and send events/metrics.
    """
    # Protective defaults for empty ENV/settings
    timeout_sec = int(getattr(settings, "SETTLEMENT_TIMEOUT_SEC", 300) or 300)
    min_ratio_for_ok = dec("0.999")  # Almost complete fill is "ok" when closing

    try:
        open_rows = storage.orders.list_open(symbol) or []
    except Exception:
        _log.error("list_open_failed", extra={"symbol": symbol}, exc_info=True)
        open_rows = []

    if not open_rows:
        return

    pfh = PartialFillHandler(bus=bus)

    for row in open_rows:
        await _process_single_order(row, broker, storage, bus, pfh, symbol, timeout_sec, min_ratio_for_ok)
