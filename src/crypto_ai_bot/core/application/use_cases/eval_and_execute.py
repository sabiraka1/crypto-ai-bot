from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, OrderDTO
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.utils.decimal import dec, q_step
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.budget_guard import check as budget_check
from crypto_ai_bot.utils.exceptions import IdempotencyError

_log = get_logger("usecase.eval_execute")

@dataclass
class EvalResult:
    action: str
    reason: str
    quote_amount: Optional[Decimal] = None
    base_amount: Optional[Decimal] = None

async def _emit(bus: AsyncEventBus, topic: str, payload: Dict[str, Any], key: Optional[str] = None) -> None:
    try:
        await bus.publish(topic, payload, key=key or payload.get("symbol"))
    except Exception:
        pass

def _deterministic_coid(exchange: str, *, symbol: str, side: str, qty: Decimal, unit: str, bucket_ms: int) -> str:
    from crypto_ai_bot.utils.time import now_ms
    bucket = int(now_ms() // max(1, int(bucket_ms)))
    qty_q = str(q_step(dec(str(qty)), 8))
    return f"idem:{exchange}:{symbol}:{side}:{unit}:{qty_q}:{bucket}"

def _evaluate_strategy(*, symbol: str, storage: Storage, settings: Any,
                       risk_manager: RiskManager, fixed_quote_amount: Decimal,
                       force_action: Optional[str]) -> EvalResult:
    force = (force_action or "").lower().strip()
    if force == "buy":
        amt_q = dec(str(fixed_quote_amount))
        if amt_q > 0:
            return EvalResult(action="buy", reason="force_action", quote_amount=amt_q)
    elif force == "sell":
        pos = storage.positions.get_position(symbol)
        base = dec(str(pos.base_qty or 0))
        if base > 0:
            return EvalResult(action="sell", reason="force_action", base_amount=base)
    return EvalResult(action="hold", reason="no_signal")

async def eval_and_execute(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    force_action: Optional[str],
    risk_manager: RiskManager,
    protective_exits: ProtectiveExits,
    settings: Any,
    fee_estimate_pct: Decimal = dec("0"),
) -> Optional[OrderDTO]:
    # 0) риск по комиссии (если задан верхний порог)
    try:
        max_fee = dec(str(getattr(settings, "RISK_MAX_FEE_PCT", "0") or "0"))
        if max_fee > 0 and fee_estimate_pct > max_fee:
            payload = {"symbol": symbol, "reason": f"risk_block:max_fee_pct>{max_fee}", "ts_ms": now_ms()}
            _log.warning("trade_blocked_risk_fee", extra=payload)
            inc("risk_block_total", symbol=symbol, why="max_fee_pct")
            await _emit(bus, "trade.blocked", payload, key=symbol)
            return None
    except Exception:
        pass

    # 1) стратегия
    plan = _evaluate_strategy(
        symbol=symbol, storage=storage, settings=settings, risk_manager=risk_manager,
        fixed_quote_amount=fixed_quote_amount, force_action=force_action,
    )
    if plan.action == "hold":
        _log.info("hold", extra={"symbol": symbol, "reason": plan.reason})
        return None

    # 2) budget gate (единый guard)
    over = budget_check(storage, symbol, settings)
    if over:
        payload = {"symbol": symbol, "reason": "budget_exceeded", **over, "ts_ms": now_ms()}
        _log.warning("trade_blocked_budget", extra=payload)
        inc("budget_block_total", symbol=symbol, kind=over.get("type", ""))
        await _emit(bus, "budget.exceeded", payload, key=symbol)  # NEW: отдельное событие
        await _emit(bus, "trade.blocked", payload, key=symbol)
        return None

    # 3) risk gate (позиционный и дневной PnL)
    try:
        ok, why = risk_manager.allow(symbol=symbol, action=plan.action,
                                     quote_amount=plan.quote_amount, base_amount=plan.base_amount)
        if not ok:
            payload = {"symbol": symbol, "reason": f"risk_block:{why or ''}", "ts_ms": now_ms()}
            _log.warning("trade_blocked_risk", extra=payload)
            inc("risk_block_total", symbol=symbol, why=str(why or ""))
            await _emit(bus, "trade.blocked", payload, key=symbol)
            return None
    except Exception as exc:
        payload = {"symbol": symbol, "reason": "risk_exception", "error": str(exc), "ts_ms": now_ms()}
        _log.error("trade_blocked_risk_exception", extra=payload)
        inc("risk_block_total", symbol=symbol, why="exception")
        await _emit(bus, "trade.blocked", payload, key=symbol)
        return None

    # 4) подготовка и идемпотентность
    quote_ccy = parse_symbol(symbol).quote
    order: Optional[OrderDTO] = None
    side = plan.action

    if side == "buy":
        amt_q = dec(str(plan.quote_amount or 0))
        if amt_q <= 0:
            raise ValueError("quote_amount must be > 0")
        coid = _deterministic_coid(exchange, symbol=symbol, side="buy",
                                   qty=amt_q, unit="quote", bucket_ms=int(idempotency_bucket_ms))
    elif side == "sell":
        amt_b = dec(str(plan.base_amount or 0))
        if amt_b <= 0:
            raise ValueError("base_amount must be > 0")
        coid = _deterministic_coid(exchange, symbol=symbol, side="sell",
                                   qty=amt_b, unit="base", bucket_ms=int(idempotency_bucket_ms))
    else:
        return None

    # explicit idempotency check
    idem = getattr(storage, "idempotency", None)
    try:
        if idem and hasattr(idem, "check_and_store"):
            ok = idem.check_and_store(coid, ttl=int(idempotency_ttl_sec))
            if not ok:
                raise IdempotencyError("duplicate clientOrderId")
    except IdempotencyError as exc:
        payload = {"symbol": symbol, "reason": "idempotent_duplicate", "client_order_id": coid, "ts_ms": now_ms()}
        _log.warning("trade_blocked_idem", extra=payload)
        inc("idempotency_block_total", symbol=symbol)
        await _emit(bus, "trade.blocked", payload, key=symbol)
        return None

    # 5) исполнение
    try:
        if side == "buy":
            order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=amt_q, client_order_id=coid)
        else:
            order = await broker.create_market_sell_base(symbol=symbol, base_amount=amt_b, client_order_id=coid)
    except Exception as exc:
        payload = {"symbol": symbol, "reason": "broker_exception", "error": str(exc), "ts_ms": now_ms()}
        _log.error("trade_failed_broker", extra=payload)
        inc("broker_exception_total", symbol=symbol)
        await _emit(bus, "trade.failed", payload, key=symbol)
        return None

    if not order:
        payload = {"symbol": symbol, "reason": "no_order_returned", "ts_ms": now_ms()}
        _log.error("trade_failed_empty", extra=payload)
        inc("broker_exception_total", symbol=symbol)
        await _emit(bus, "trade.failed", payload, key=symbol)
        return None

    # 6) запись сделки
    try:
        storage.trades.add_from_order(order)
    except Exception as exc:
        _log.error("trade_persist_error", extra={"symbol": symbol, "error": str(exc)})
        inc("persist_error_total", symbol=symbol)

    # 6.1 аудит (best-effort)
    try:
        audit = getattr(storage, "audit", None)
        if audit and hasattr(audit, "log"):
            audit.log("trade", {
                "symbol": symbol, "side": order.side, "amount": str(order.amount),
                "price": str(order.price or ""), "cost": str(order.cost or ""),
                "fee_quote": str(getattr(order, "fee_quote", "")),
                "client_order_id": order.client_order_id, "broker_order_id": order.id,
                "ts_ms": now_ms(),
            })
    except Exception:
        pass

    # 7) событие об успехе
    payload = {
        "symbol": symbol,
        "side": order.side,
        "amount": str(order.amount),
        "price": str(order.price or ""),
        "cost": str(order.cost or ""),
        "fee_quote": str(getattr(order, "fee_quote", "")),
        "client_order_id": order.client_order_id,
        "broker_order_id": order.id,
        "quote_ccy": quote_ccy,
        "fee_estimate_pct": str(fee_estimate_pct),
        "ts_ms": now_ms(),
    }
    _log.info("trade_completed", extra=payload)
    inc("trade_completed_total", symbol=symbol, side=order.side)
    await _emit(bus, "trade.completed", payload, key=symbol)

    # 8) частичные исполнения (как было)
    try:
        if (order.filled or dec("0")) < (order.amount or dec("0")):
            from crypto_ai_bot.core.application.use_cases.partial_fills import PartialFillHandler
            handler = PartialFillHandler(bus)
            follow = await handler.handle(order, broker)
            if follow:
                storage.trades.add_from_order(follow)
                inc("partial_followup_total", symbol=symbol, side=follow.side)
    except Exception as exc:
        _log.error("partial_followup_failed", extra={"error": str(exc)})
        inc("partial_followup_errors_total", symbol=symbol)

    return order
