from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from ..signals._build import build_market_context
from ..use_cases.evaluate import evaluate
from ..use_cases.place_order import place_market_buy_quote, place_market_sell_base
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..events.bus import AsyncEventBus
from ..events import topics
from ..brokers.base import IBroker
from ..storage.facade import Storage
from ...utils.metrics import inc, timer
from ...utils.logging import get_logger

_log = get_logger("use_cases.eval_and_execute")


def _normalize_risk_result(res: Any) -> Tuple[bool, str]:
    """Приводим ответ RiskManager к (bool, reason). Поддерживаем dict/tuple/bool/объект с атрибутами."""
    try:
        if isinstance(res, dict):
            allowed = bool(res.get("ok", res.get("allowed")))
            return allowed, str(res.get("reason", "")) if "reason" in res else ""
        if isinstance(res, (tuple, list)):
            if not res:
                return False, ""
            if len(res) == 1:
                return bool(res[0]), ""
            return bool(res[0]), "" if res[1] is None else str(res[1])
        if hasattr(res, "ok"):
            return bool(getattr(res, "ok")), "" if getattr(res, "reason", None) is None else str(getattr(res, "reason"))
        return bool(res), ""
    except Exception:
        return False, "risk_result_unparseable"


async def eval_and_execute(
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
) -> Dict[str, Any]:
    """Единый шаг: evaluate → risk.check → place_order → exits.ensure (+метрики)."""
    external = external or {}

    # 1) Сбор контекста + решение
    with timer("trade_eval_ms", {"symbol": symbol}):
        ctx = await build_market_context(symbol=symbol, broker=broker, storage=storage)
        eval_res = await evaluate(symbol, storage=storage, broker=broker, bus=bus)
        decision = (force_action or eval_res.decision) or "hold"
        explain = {**eval_res.features, "context": ctx}
    inc("trade_decisions_total", {"decision": decision})

    # 2) Риски
    if risk_manager is not None:
        with timer("trade_risk_ms", {"symbol": symbol}):
            quote_amount: Optional[Decimal] = None
            base_amount: Optional[Decimal] = None
            if decision == "buy":
                quote_amount = Decimal(str(fixed_quote_amount))
            elif decision == "sell":
                try:
                    base_amount = storage.positions.get_base_qty(symbol)
                except Exception:
                    base_amount = None
            try:
                ticker = await broker.fetch_ticker(symbol)
            except Exception:
                ticker = None

            risk_raw = await risk_manager.check(
                symbol=symbol,
                side=decision,
                quote_amount=quote_amount,
                base_amount=base_amount,
                ticker=ticker,  # type: ignore[arg-type]
            )
            allowed, reason = _normalize_risk_result(risk_raw)

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

    await bus.publish(topics.TRADE_COMPLETED, {"symbol": symbol, "decision": decision, "result": result}, key=symbol)
    return {"executed": True, "decision": decision, "result": result, "explain": explain}
