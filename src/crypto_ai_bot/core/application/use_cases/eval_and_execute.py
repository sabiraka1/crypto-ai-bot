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

_log = get_logger("usecase.eval_execute")


@dataclass
class EvalResult:
    action: str                    # "buy" | "sell" | "hold"
    reason: str
    quote_amount: Optional[Decimal] = None  # для buy (в валюте котировки)
    base_amount: Optional[Decimal] = None   # для sell (в базовой валюте)


# ----------------------- helpers -----------------------
def _budget_blocked(storage: Storage, symbol: str, settings: Any) -> Tuple[bool, Dict[str, str]]:
    """Проверка safety-budget (дублирующая защита на случай вызовов вне оркестратора)."""
    max_orders_5m = float(getattr(settings, "BUDGET_MAX_ORDERS_5M", 0) or 0)
    if max_orders_5m > 0:
        cnt5 = storage.trades.count_orders_last_minutes(symbol, 5)
        if cnt5 >= max_orders_5m:
            return True, {"type": "max_orders_5m", "count_5m": str(cnt5), "limit": str(int(max_orders_5m))}

    max_turnover = dec(str(getattr(settings, "BUDGET_MAX_TURNOVER_DAY_QUOTE", "0") or "0"))
    if max_turnover > 0:
        day_turn = storage.trades.daily_turnover_quote(symbol)
        if day_turn >= max_turnover:
            return True, {"type": "max_turnover_day", "turnover": str(day_turn), "limit": str(max_turnover)}

    return False, {}


def _deterministic_coid(exchange: str, *, symbol: str, side: str, qty: Decimal, unit: str, bucket_ms: int) -> str:
    """
    Делаем тот же детерминированный clientOrderId, что и брокер (на случай,
    если захотим явно проставить coid при вызове create_order).
    Формат: idem:{exchange}:{symbol}:{side}:{unit}:{qty_q}:{bucket}
    """
    bucket = int(now_ms() // max(1, int(bucket_ms)))
    qty_q = str(q_step(dec(str(qty)), 8))
    return f"idem:{exchange}:{symbol}:{side}:{unit}:{qty_q}:{bucket}"


async def _emit(bus: AsyncEventBus, topic: str, payload: Dict[str, Any], key: Optional[str] = None) -> None:
    try:
        await bus.publish(topic, payload, key=key or payload.get("symbol"))
    except Exception:
        pass


# ----------------------- strategy stub -----------------------
def _evaluate_strategy(*, symbol: str, storage: Storage, settings: Any,
                       risk_manager: RiskManager, fixed_quote_amount: Decimal,
                       force_action: Optional[str]) -> EvalResult:
    """
    Минимальный, но безопасный план действий:
    - если передан force_action: выполнить его
      - "buy": покупаем fixed_quote_amount котировки
      - "sell": продаём весь базовый остаток позиции
      - иное/None: hold
    - если force_action нет — HOLD (логика стратегии может быть подключена позже)
    """
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


# ----------------------- main use-case -----------------------
async def eval_and_execute(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,             # оставляем для совместимости; TTL реализуем БД-дедупом
    force_action: Optional[str],
    risk_manager: RiskManager,
    protective_exits: ProtectiveExits,
    settings: Any,
    fee_estimate_pct: Decimal = dec("0"),
) -> Optional[OrderDTO]:
    """
    Единый сценарий: оценка -> проверка рисков/бюджета -> исполнение (идемпотентно) -> запись/события.
    - Жёсткая идемпотентность обеспечивается UNIQUE(client_order_id) на trades, плюс детерминированным coid.
    - Дублирующий safety-budget на случай вызова вне оркестратора.
    """
    # 1) стратегия / решение
    plan = _evaluate_strategy(
        symbol=symbol,
        storage=storage,
        settings=settings,
        risk_manager=risk_manager,
        fixed_quote_amount=fixed_quote_amount,
        force_action=force_action,
    )

    if plan.action == "hold":
        _log.info("hold", extra={"symbol": symbol, "reason": plan.reason})
        return None

    # 2) дублирующий budget guard
    blocked, info = _budget_blocked(storage, symbol, settings)
    if blocked:
        payload = {"symbol": symbol, "reason": "budget_exceeded", **info, "ts_ms": now_ms()}
        _log.warning("trade_blocked_budget", extra=payload)
        await _emit(bus, "trade.blocked", payload, key=symbol)
        return None

    # 3) валидация RiskManager (например, max_position, stop-switch)
    try:
        ok, why = risk_manager.allow(symbol=symbol, action=plan.action,
                                     quote_amount=plan.quote_amount, base_amount=plan.base_amount)
        if not ok:
            payload = {"symbol": symbol, "reason": f"risk_block:{why or ''}", "ts_ms": now_ms()}
            _log.warning("trade_blocked_risk", extra=payload)
            await _emit(bus, "trade.blocked", payload, key=symbol)
            return None
    except Exception as exc:
        payload = {"symbol": symbol, "reason": "risk_exception", "error": str(exc), "ts_ms": now_ms()}
        _log.error("trade_blocked_risk_exception", extra=payload)
        await _emit(bus, "trade.blocked", payload, key=symbol)
        return None

    # 4) исполнение (детерминированный clientOrderId на случай ретраев)
    quote_ccy = parse_symbol(symbol).quote
    order: Optional[OrderDTO] = None

    try:
        if plan.action == "buy":
            amt_q = dec(str(plan.quote_amount or 0))
            if amt_q <= 0:
                raise ValueError("quote_amount must be > 0")
            coid = _deterministic_coid(exchange, symbol=symbol, side="buy",
                                       qty=amt_q, unit="quote", bucket_ms=int(idempotency_bucket_ms))
            order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=amt_q, client_order_id=coid)

        elif plan.action == "sell":
            amt_b = dec(str(plan.base_amount or 0))
            if amt_b <= 0:
                raise ValueError("base_amount must be > 0")
            coid = _deterministic_coid(exchange, symbol=symbol, side="sell",
                                       qty=amt_b, unit="base", bucket_ms=int(idempotency_bucket_ms))
            order = await broker.create_market_sell_base(symbol=symbol, base_amount=amt_b, client_order_id=coid)

        else:
            return None

    except Exception as exc:
        payload = {"symbol": symbol, "reason": "broker_exception", "error": str(exc), "ts_ms": now_ms()}
        _log.error("trade_failed_broker", extra=payload)
        await _emit(bus, "trade.failed", payload, key=symbol)
        return None

    if not order:
        payload = {"symbol": symbol, "reason": "no_order_returned", "ts_ms": now_ms()}
        _log.error("trade_failed_empty", extra=payload)
        await _emit(bus, "trade.failed", payload, key=symbol)
        return None

    # 5) запись в БД (UPSERT по client_order_id; без падений на дубликате)
    try:
        storage.trades.add_from_order(order)
    except Exception as exc:
        # даже если запись не удалась — сам ордер создан; по шине сообщим как completed с пометкой
        _log.error("trade_persist_error", extra={"symbol": symbol, "error": str(exc)})

    # 6) событие об успешной сделке
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
        "ts_ms": now_ms(),
    }
    _log.info("trade_completed", extra=payload)
    await _emit(bus, "trade.completed", payload, key=symbol)

    return order
