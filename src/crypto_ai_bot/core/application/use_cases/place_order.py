from __future__ import annotations

import hashlib
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
    side: str                  # "buy" | "sell"
    quote_amount: Decimal = dec("0")   # для buy
    base_amount: Decimal = dec("0")    # для sell
    client_order_id: Optional[str] = None


@dataclass
class PlaceOrderResult:
    ok: bool
    reason: str = ""
    order: Optional[Any] = None


def _derive_idem_key(inputs: PlaceOrderInputs, settings: Any) -> str:
    """Если client_order_id не передан — строим детерминированный ключ по payload+SESSION_RUN_ID."""
    if inputs.client_order_id:
        return f"po:{inputs.client_order_id}"
    run_id = str(getattr(settings, "SESSION_RUN_ID", "") or "")
    payload = f"{inputs.symbol}|{inputs.side}|{inputs.quote_amount}|{inputs.base_amount}|{run_id}"
    h = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"po:{h}"


async def place_order(
    *,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    settings: Any,
    inputs: PlaceOrderInputs,
) -> PlaceOrderResult:
    """
    Единый исполнитель MARKET-ордера.
    ВКЛЮЧЕНО:
      - Идемпотентность (Storage.idempotency, TTL из настроек)
      - Аудит (Storage.audit)
      - Централизованный gate по спреду/проскальзыванию (RISK_MAX_SLIPPAGE_PCT)
    """
    sym = inputs.symbol
    side = (inputs.side or "").lower()

    # ---- ИДЕМПОТЕНТНОСТЬ ----
    idem = getattr(storage, "idempotency", None)
    idem_repo = idem() if callable(idem) else None
    if idem_repo is not None:
        ttl = int(getattr(settings, "IDEMPOTENCY_TTL_SEC", 60) or 60)
        key = _derive_idem_key(inputs, settings)
        ok_first = False
        try:
            ok_first = bool(idem_repo.check_and_store(key, ttl))
        except Exception as e:
            _log.warning("idem_check_failed", extra={"key": key, "error": str(e)})
        if not ok_first:
            inc("trade.blocked", {"reason": "idempotent_duplicate"})
            await bus.publish("trade.blocked", {"symbol": sym, "reason": "idempotent_duplicate"})
            return PlaceOrderResult(ok=False, reason="idempotent_duplicate")

    # ---- АУДИТ (вход) ----
    audit = getattr(storage, "audit", None)
    audit_repo = audit() if callable(audit) else None
    try:
        if audit_repo is not None:
            audit_repo.write("place_order.request", {
                "symbol": sym, "side": side,
                "quote_amount": str(inputs.quote_amount),
                "base_amount": str(inputs.base_amount),
                "client_order_id": inputs.client_order_id or "",
            })
    except Exception as e:
        _log.warning("audit_failed_in", extra={"error": str(e)})

    # ---- Slippage / spread gate (ЕДИНСТВЕННОЕ место) ----
    try:
        max_slip_pct = Decimal(str(getattr(settings, "RISK_MAX_SLIPPAGE_PCT", "") or "0"))
    except Exception:
        max_slip_pct = dec("0")
    if max_slip_pct > 0:
        try:
            t = await broker.fetch_ticker(sym)
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
            _log.warning("slippage_check_failed", extra={"symbol": sym, "error": str(exc)})

    # ---- Исполнение ----
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

        # запись сделки и события
        storage.trades.add_from_order(order)
        await bus.publish("trade.completed", {
            "symbol": sym, "side": side,
            "amount": str(getattr(order, "amount", "")),
            "price": str(getattr(order, "price", "")),
            "cost": str(getattr(order, "cost", "")),
            "fee_quote": str(getattr(order, "fee_quote", "")),
        })

        # ---- АУДИТ (успех) ----
        try:
            if audit_repo is not None:
                audit_repo.write("place_order.success", {
                    "symbol": sym, "side": side,
                    "order_id": getattr(order, "id", ""),
                    "client_order_id": getattr(order, "client_order_id", ""),
                    "amount": str(getattr(order, "amount", "")),
                    "price": str(getattr(order, "price", "")),
                    "cost": str(getattr(order, "cost", "")),
                })
        except Exception as e:
            _log.warning("audit_failed_out", extra={"error": str(e)})

        return PlaceOrderResult(ok=True, order=order)

    except Exception as exc:
        _log.error("place_order_failed", extra={"symbol": sym, "side": side, "error": str(exc)})
        inc("trade.failed", {"where": "broker"})
        await bus.publish("trade.failed", {"symbol": sym, "side": side, "error": str(exc)})

        # ---- АУДИТ (ошибка) ----
        try:
            if audit_repo is not None:
                audit_repo.write("place_order.error", {
                    "symbol": sym, "side": side, "error": str(exc)
                })
        except Exception:
            pass

        return PlaceOrderResult(ok=False, reason="broker_exception")
