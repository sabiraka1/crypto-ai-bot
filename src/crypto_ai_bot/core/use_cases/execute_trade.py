from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..signals._build import build_market_context  # контекст остаётся
from ..use_cases.evaluate import evaluate          # возвращает EvaluationResult
from ..use_cases.place_order import (
    place_market_buy_quote,
    place_market_sell_base,
)
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..events.bus import AsyncEventBus
from ..events import topics
from ..brokers.base import IBroker
from ..storage.facade import Storage
from ...utils.metrics import inc, timer
from ...utils.logging import get_logger

_log = get_logger("use_cases.execute_trade")


async def execute_trade(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    fixed_quote_amount,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    risk_manager: Optional[RiskManager] = None,
    protective_exits: Optional[ProtectiveExits] = None,
    external: Optional[Dict[str, Any]] = None,
    force_action: Optional[str] = None,
    force_amount: Optional[Any] = None,  # совместимость с вызывающей стороной
) -> Dict[str, Any]:
    """Единый шаг: evaluate → risk.check → place_order → exits.ensure (+метрики)."""

    external = external or {}

    # 1) Сбор контекста + решение
    with timer("trade_eval_ms", {"symbol": symbol}):
        ctx = await build_market_context(symbol=symbol, broker=broker, storage=storage)
        # Приводим к фактической сигнатуре evaluate(): возвращает EvaluationResult
        eval_res = await evaluate(symbol, storage=storage, broker=broker, bus=bus)
        decision = force_action or eval_res.decision
        explain = {**eval_res.features, "context": ctx}
    inc("trade_decisions_total", {"decision": decision})

    # 2) Риски (если передан менеджер)
    if risk_manager is not None:
        with timer("trade_risk_ms", {"symbol": symbol}):
            allowed, reason = await risk_manager.check(symbol=symbol, action=decision, evaluation=explain)
        if not allowed:
            inc("trade_blocked_total", {"reason": reason or "unknown"})
            await bus.publish(topics.RISK_BLOCKED, {"symbol": symbol, "decision": decision, "reason": reason}, key=symbol)
            return {"executed": False, "decision": decision, "why": f"blocked:{reason}", "explain": explain}

    # 3) Ордер
    result: Dict[str, Any] = {}
    with timer("trade_place_ms", {"symbol": symbol, "decision": decision}):
        if decision == "buy":
            result = await place_market_buy_quote(
                symbol,
                fixed_quote_amount,
                exchange=exchange,
                storage=storage,
                broker=broker,
                bus=bus,
                idempotency_bucket_ms=idempotency_bucket_ms,
                idempotency_ttl_sec=idempotency_ttl_sec,
            )
        elif decision == "sell":
            base_qty = storage.positions.get_base_qty(symbol)
            if base_qty and base_qty > 0:
                result = await place_market_sell_base(
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
                result = {"skipped": True, "reason": "no_position"}
        else:
            result = {"skipped": True, "reason": "hold"}

    # 4) Защитные выходы
    if protective_exits is not None:
        with timer("trade_exits_ms", {"symbol": symbol}):
            try:
                await protective_exits.ensure(symbol=symbol)
            except Exception as exc:
                _log.error("exits_ensure_failed", extra={"error": str(exc)})

    # событие для наблюдаемости
    await bus.publish(topics.TRADE_COMPLETED, {"symbol": symbol, "decision": decision, "result": result}, key=symbol)
    return {"executed": True, "decision": decision, "result": result, "explain": explain}