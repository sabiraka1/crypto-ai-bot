# src/crypto_ai_bot/core/application/use_cases/partial_fills.py
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, OrderDTO
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("usecase.partial_fills")


class PartialFillHandler:
    """Обработка частичных исполнений ордеров."""

    def __init__(self, bus: AsyncEventBus) -> None:
        self.bus = bus

    async def handle(self, order: OrderDTO, broker: IBroker) -> Optional[OrderDTO]:
        """Возвращает новый ордер, если было дозаявление / переразмещение; иначе None."""
        try:
            if order.amount <= 0:
                return None

            amount = dec(str(order.amount or 0))
            filled = dec(str(order.filled or 0))
            if amount <= 0:
                return None

            filled_pct = float(filled / amount) if amount > 0 else 1.0

            # ≥95%: принимаем остаток как есть
            if filled_pct >= 0.95:
                await self._emit("order.partial_accepted", {"order_id": order.id, "filled_pct": filled_pct})
                return None

            # 50–95%: дозаявить ИМЕННО ОСТАТОК
            if filled_pct >= 0.50:
                remaining = amount - filled
                if remaining <= 0:
                    return None

                if (order.side or "").lower() == "buy":
                    t = await broker.fetch_ticker(order.symbol)
                    px = t.ask or t.last or dec("0")
                    if px <= 0:
                        return None
                    remaining_quote = remaining * px
                    new_order = await broker.create_market_buy_quote(
                        symbol=order.symbol,
                        quote_amount=remaining_quote,
                        client_order_id=make_client_order_id("partial", order.symbol),
                    )
                else:  # sell
                    new_order = await broker.create_market_sell_base(
                        symbol=order.symbol,
                        base_amount=remaining,
                        client_order_id=make_client_order_id("partial", order.symbol),
                    )

                await self._emit("order.partial_topped_up", {
                    "original": order.id,
                    "new": getattr(new_order, "id", None),
                    "filled_pct": filled_pct
                })
                return new_order

            # <50%: отменить и переразместить ТОЛЬКО ОСТАТОК
            cancel = getattr(broker, "cancel_order", None)
            if callable(cancel):
                try:
                    await cancel(order.id)
                except Exception:
                    pass

            remaining = amount - filled
            if remaining <= 0:
                return None

            if (order.side or "").lower() == "buy":
                t = await broker.fetch_ticker(order.symbol)
                px = t.ask or t.last or dec("0")
                if px <= 0:
                    return None
                quote_amt = remaining * px
                new_order = await broker.create_market_buy_quote(
                    symbol=order.symbol,
                    quote_amount=quote_amt,
                    client_order_id=f"reorder-{now_ms()}",
                )
            else:
                new_order = await broker.create_market_sell_base(
                    symbol=order.symbol,
                    base_amount=remaining,
                    client_order_id=f"reorder-{now_ms()}",
                )

            await self._emit("order.partial_reordered", {
                "original": order.id,
                "new": getattr(new_order, "id", None),
                "filled_pct": filled_pct
            })
            return new_order

        except Exception as exc:
            _log.error("partial_fill_handle_failed", extra={"error": str(exc)})
            return None

    async def _emit(self, topic: str, payload: dict) -> None:
        try:
            await self.bus.publish(topic, payload, key=payload.get("order_id"))
        except Exception:
            pass
