## `execute_trade.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from ..events.bus import AsyncEventBus
from ..brokers.base import IBroker
from ..storage.facade import Storage
from ..events import topics
from ...utils.logging import get_logger
from ...utils.metrics import inc, timer
from .evaluate import evaluate, EvaluationResult
from .place_order import place_market_buy_quote, place_market_sell_base, PlaceOrderResult

_log = get_logger("use_cases.execute_trade")

@dataclass(frozen=True)
class ExecuteResult:
    evaluation: EvaluationResult
    action: str  # 'buy' | 'sell' | 'hold'
    order: Optional[PlaceOrderResult]

async def execute_trade(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: Optional[AsyncEventBus],
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    risk_manager: Optional[object] = None,
    protective_exits: Optional[object] = None,
    force_action: Optional[str] = None,  # 'buy' | 'sell' чтобы пропустить политику
    force_amount: Optional[Decimal] = None,
) -> ExecuteResult:
    
    # 1) Построение фич/тикера/контекста
    with timer("build_features_ms", {"symbol": symbol}, unit="ms"):
        ev = await evaluate(symbol, storage=storage, broker=broker, bus=bus)
    
    # 2) Принятие решения
    with timer("decide_ms", {"symbol": symbol}, unit="ms"):
        action = force_action or ev.decision
    
    # 3) Риск-чек
    if action in {"buy", "sell"} and risk_manager is not None:
        with timer("risk_check_ms", {"symbol": symbol}, unit="ms"):
            try:
                allowed, reason = await _risk_check(risk_manager, symbol=symbol, action=action, evaluation=ev)
            except Exception as exc:
                _log.error("risk_failed", extra={"error": str(exc)})
                allowed, reason = False, "risk_error"
        
        if not allowed:
            if bus:
                await bus.publish(topics.RISK_BLOCKED, {"symbol": symbol, "action": action, "reason": reason}, key=symbol)
            inc("risk_blocked", {"action": action})
            return ExecuteResult(evaluation=ev, action="hold", order=None)
    
    # 4) Размещение ордеров
    order_res: Optional[PlaceOrderResult] = None
    
    if action == "buy":
        with timer("usecase_place_buy_ms", {"symbol": symbol}, unit="ms"):
            quote = force_amount if force_amount is not None else fixed_quote_amount
            order_res = await place_market_buy_quote(
                symbol,
                quote,
                exchange=exchange,
                storage=storage,
                broker=broker,
                bus=bus,
                idempotency_bucket_ms=idempotency_bucket_ms,
                idempotency_ttl_sec=idempotency_ttl_sec,
            )
    elif action == "sell":
        with timer("usecase_place_sell_ms", {"symbol": symbol}, unit="ms"):
            if force_amount is None:
                base_qty = storage.positions.get_base_qty(symbol)
            else:
                base_qty = force_amount
            if base_qty > 0:
                order_res = await place_market_sell_base(
                    symbol,
                    base_qty,
                    exchange=exchange,
                    storage=storage,
                    broker=broker,
                    bus=bus,
                    idempotency_bucket_ms=idempotency_bucket_ms,
                    idempotency_ttl_sec=idempotency_ttl_sec,
                )
            else:
                _log.info("nothing_to_sell", extra={"symbol": symbol})
                action = "hold"
    
    # 5) Защитные выходы
    if order_res and order_res.order and protective_exits is not None and action == "buy":
        try:
            await _ensure_exits(protective_exits, symbol=symbol, order=order_res.order)
        except Exception as exc:
            _log.error("protective_exit_error", extra={"error": str(exc)})
    
    return ExecuteResult(evaluation=ev, action=action, order=order_res)

async def _risk_check(risk_manager, **kwargs):  # pragma: no cover - будет реализовано на шаге 7
    return await risk_manager.check(**kwargs)

async def _ensure_exits(protective_exits, **kwargs):  # pragma: no cover - будет реализовано на шаге 7
    return await protective_exits.ensure(**kwargs)