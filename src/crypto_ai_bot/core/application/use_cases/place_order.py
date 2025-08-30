from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.place_order")


@dataclass
class PlaceOrderInputs:
    symbol: str
    side: str                 # "buy" | "sell"  (стратегия long-only: используем "buy")
    quote_amount: Decimal = dec("0")   # для market buy (в котируемой валюте)
    base_amount: Decimal = dec("0")    # для market sell (в базовой), на будущее
    client_order_id: Optional[str] = None


@dataclass
class PlaceOrderResult:
    ok: bool
    reason: str = ""
    order: Optional[Any] = None


async def place_order(
    *,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    settings: Any,
    inputs: PlaceOrderInputs,
) -> PlaceOrderResult:
    """Единое исполнение рыночного ордера через порты. Подключён слippage-gate."""
    sym = inputs.symbol
    side = (inputs.side or "").lower()

    # --- Slippage gate (используем спред как прокси) ---
    # RISK_MAX_SLIPPAGE_PCT: если не задан, пропускаем проверку.
    try:
        max_slip_pct = Decimal(str(getattr(settings, "RISK_MAX_SLIPPAGE_PCT", "") or "0"))
    except Exception:
        max_slip_pct = dec("0")

    if max_slip_pct > 0:
        try:
            t = await broker.fetch_ticker(sym)  # порт брокера
            bid = dec(str(t.get("bid") or "0"))
            ask = dec(str(t.get("ask") or "0"))
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * 100
                if spread_pct > max_slip_pct:
                    reason = f"slippage_exceeds:{spread_pct:.4f}%>{max_slip_pct}%"
                    inc("trade.blocked", {"reason": "slippage"})
                    await bus.publish("trade.blocked", {"symbol": sym, "reason": reason})
                    return PlaceOrderResult(ok=False, reason=reason)
        except Exception as exc:
            # при ошибке котировок не блокируем, но логируем
            _log.warning("slippage_check_failed", extra={"symbol": sym, "error": str(exc)})

    # --- Исполнение ---
    try:
        if side == "buy":
            q = inputs.quote_amount if inputs.quote_amount > 0 else dec(str(getattr(settings, "FIXED_AMOUNT", 0) or 0))
            inc("broker.order.create", {"side": "buy"})
            order = await broker.create_market_buy_quote(symbol=sym, quote_amount=q, client_order_id=inputs.client_order_id)
        elif side == "sell":
            b = inputs.base_amount if inputs.base_amount > 0 else dec("0")
            inc("broker.order.create", {"side": "sell"})
            order = await broker.create_market_sell_base(symbol=sym, base_amount=b, client_order_id=inputs.client_order_id)
        else:
            return PlaceOrderResult(ok=False, reason="invalid_side")

        # запись сделки в БД (репозиторий сам обновит позицию)
        storage.trades.add_from_order(order)
        await bus.publish("trade.completed", {
            "symbol": sym, "side": side,
            "amount": str(getattr(order, "amount", "")),
            "price": str(getattr(order, "price", "")),
            "cost": str(getattr(order, "cost", "")),
            "fee_quote": str(getattr(order, "fee_quote", "")),
        })
        return PlaceOrderResult(ok=True, order=order)

    except Exception as exc:
        _log.error("place_order_failed", extra={"symbol": sym, "side": side, "error": str(exc)})
        inc("trade.failed", {"where": "broker"})
        await bus.publish("trade.failed", {"symbol": sym, "side": side, "error": str(exc)})
        return PlaceOrderResult(ok=False, reason="broker_exception")
