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

    async def handle(self, order: OrderLike, broker: BrokerPort) -> OrderLike | None:
        """
        Если частично исполнилось меньше 95% — добиваем остаток по рынку.
        Для buy amount трактуем как quote, для sell — как base (как в текущей модели).
        """
        try:
            filled = _dec(getattr(order, "filled", 0))
            amount = _dec(getattr(order, "amount", 0))
            if amount <= 0:
                return None

            if _ratio(filled, amount) >= dec("0.95"):
                return None

            remaining = amount - filled
            symbol = getattr(order, "symbol", "") or ""
            side = (getattr(order, "side", "") or "").lower()
            base_client_id = getattr(order, "client_order_id", "") or ""
            # чтобы не зациклиться, follow-up создаём один раз
            if base_client_id.endswith("-pf"):
                return None

            if side == "buy":
                follow = await broker.create_market_buy_quote(
                    symbol=symbol,
                    quote_amount=remaining,
                    client_order_id=f"{base_client_id}-pf",
                )
            else:
                follow = await broker.create_market_sell_base(
                    symbol=symbol,
                    base_amount=remaining,
                    client_order_id=f"{base_client_id}-pf",
                )

            await self.bus.publish(
                EVT.TRADE_PARTIAL_FOLLOWUP,
                {
                    "parent_client_order_id": base_client_id,
                    "follow_client_order_id": getattr(follow, "client_order_id", ""),
                    "symbol": symbol,
                    "side": side,
                    "remaining": str(remaining),
                },
            )
            inc("partial_followup_total", symbol=symbol, side=side)
            return cast(OrderLike, follow)
        except Exception as exc:
            _log.error("partial_followup_failed", extra={"error": str(exc)})
            inc("partial_followup_errors_total")
            return None


async def settle_orders(
    symbol: str,
    storage: Any,
    broker: BrokerPort,
    bus: EventBusPort,
    settings: Any,
) -> None:
    """
    Обходит открытые ордера по symbol, тянет фактический статус с биржи,
    обновляет локальное состояние, делает follow-up при частичном исполнении,
    и шлёт события/метрики.

    Требования к storage:
      - storage.orders.list_open(symbol) -> list[dict]
      - storage.orders.mark_closed(broker_order_id, filled)
      - storage.orders.update_progress(broker_order_id, filled)   # добавлено в репозиторий
      - storage.trades.add_from_order(order)                      # best-effort
    """
    # Защитные дефолты — чтобы не падать на пустых ENV/настройках
    timeout_sec = int(getattr(settings, "SETTLEMENT_TIMEOUT_SEC", 300) or 300)
    min_ratio_for_ok = dec("0.999")  # почти полное исполнение «ок» при закрытии

    try:
        open_rows = storage.orders.list_open(symbol) or []
    except Exception:
        _log.error("list_open_failed", extra={"symbol": symbol}, exc_info=True)
        open_rows = []

    if not open_rows:
        return

    pfh = PartialFillHandler(bus=bus)

    for row in open_rows:
        broker_order_id = (row.get("broker_order_id") or "") if isinstance(row, dict) else None
        client_order_id = (row.get("client_order_id") or "") if isinstance(row, dict) else None
        side = (row.get("side") or "").lower() if isinstance(row, dict) else ""
        ts_ms = int(row.get("ts_ms") or 0) if isinstance(row, dict) else 0
        age_sec = 0
        try:
            import time

            age_sec = max(0, int(time.time()) - ts_ms // 1000) if ts_ms else 0
        except Exception:
            pass

        # 1) Тянем фактический статус с биржи
        fetched = None
        try:
            if broker_order_id:
                fetched = await broker.fetch_order(broker_order_id, symbol)
            elif client_order_id and hasattr(broker, "fetch_order_by_client_id"):
                fetched = await broker.fetch_order_by_client_id(client_order_id, symbol)  # type: ignore[attr-defined]
            else:
                _log.warning("fetch_order_skipped_no_ids", extra={"symbol": symbol, "row": row})
                continue
        except Exception:
            _log.error(
                "fetch_order_failed",
                extra={"symbol": symbol, "broker_order_id": broker_order_id},
                exc_info=True,
            )
            inc("settle_fetch_order_errors_total", symbol=symbol)
            continue

        # 2) Синхронизируем прогресс (filled) и статус
        filled = _dec(getattr(fetched, "filled", row.get("filled") if isinstance(row, dict) else "0"))
        amount = _dec(getattr(fetched, "amount", row.get("amount") if isinstance(row, dict) else "0"))
        status = getattr(fetched, "status", row.get("status") if isinstance(row, dict) else "open")
        ratio = _ratio(filled, amount)

        # запишем прогресс filled (не закрывая)
        try:
            if broker_order_id and _is_open(status):
                storage.orders.update_progress(broker_order_id, str(filled))
        except Exception:
            _log.error(
                "update_progress_failed",
                extra={"symbol": symbol, "broker_order_id": broker_order_id},
                exc_info=True,
            )

        # 3) Если ордер закрыт — фиксируем и публикуем событие
        if _is_closed(status):
            try:
                if broker_order_id:
                    storage.orders.mark_closed(broker_order_id, str(filled))
            except Exception:
                _log.error(
                    "mark_closed_failed",
                    extra={"symbol": symbol, "broker_order_id": broker_order_id},
                    exc_info=True,
                )

            # best-effort: записать трейд (если ещё не записан)
            try:
                if hasattr(storage, "trades") and hasattr(storage.trades, "add_from_order"):
                    storage.trades.add_from_order(fetched)
            except Exception:
                _log.error("add_trade_failed", extra={"symbol": symbol}, exc_info=True)

            # событие settled
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

            continue

        # 4) Если ордер подвис слишком долго — шлём таймаут (не закрывая)
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

        # 5) Если частично исполнен — пробуем догнать остаток по рынку
        try:
            if ratio > dec("0") and ratio < dec("0.95"):
                await pfh.handle(cast(OrderLike, fetched), broker)
        except Exception:
            _log.error("partial_followup_call_failed", extra={"symbol": symbol}, exc_info=True)
