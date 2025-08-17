# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

from typing import Any, Dict, Optional
from decimal import Decimal

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order
from crypto_ai_bot.core.risk.manager import assess as risk_assess


def eval_and_execute(
    cfg: Settings,
    broker: Any,
    repos: Any,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    bus: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Полный цикл: evaluate -> (risk) -> place_order
    Публикует события в шину (если передана).
    """
    decision = uc_evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, bus=bus)

    action = str(decision.get("action", "hold")).lower()
    size = Decimal(str(decision.get("size", "0")))

    # Сразу публикуем «DecisionEvaluated», если это не сделал сам evaluate
    if bus:
        try:
            bus.publish({
                "type": "DecisionEvaluated",
                "symbol": symbol,
                "timeframe": timeframe,
                "score": decision.get("score"),
                "action": action,
                "size": str(size),
                "latency_ms": decision.get("latency_ms"),
                "explain": decision.get("explain") or {},
            })
        except Exception:
            pass

    # Если HOLD — заканчиваем
    if action not in ("buy", "sell") or size == 0:
        if bus:
            try:
                bus.publish({"type": "FlowFinished", "symbol": symbol, "timeframe": timeframe, "flow_latency_ms": decision.get("latency_ms")})
            except Exception:
                pass
        return {"status": "skipped", "decision": decision}

    # --- RISK ---
    ra = risk_assess(cfg, broker, repos, symbol=symbol, side=action, size=size)
    if not ra.allow:
        # безопасно: сообщаем, что заблокировано правилами
        if bus:
            try:
                bus.publish({
                    "type": "OrderFailed",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "side": action,
                    "error": "risk_blocked",
                    "reasons": ra.reasons,
                })
                bus.publish({"type": "FlowFinished", "symbol": symbol, "timeframe": timeframe})
            except Exception:
                pass
        return {"status": "blocked_risk", "reasons": ra.reasons, "decision": decision}

    # мягкое ограничение размера, если задано
    if ra.size_cap is not None and ra.size_cap > 0 and size > ra.size_cap:
        size = ra.size_cap
        decision = {**decision, "size": str(size), "explain": {**(decision.get("explain") or {}), "size_capped_by_risk": str(ra.size_cap)}}

    # --- PLACE ORDER ---
    result = uc_place_order(
        cfg,
        broker,
        positions_repo=repos.positions,
        trades_repo=repos.trades,
        audit_repo=repos.audit,
        uow=repos.uow,
        decision=decision,
        symbol=symbol,
        idem_repo=getattr(repos, "idempotency", None),
        bus=bus,
    )

    if bus:
        try:
            bus.publish({"type": "FlowFinished", "symbol": symbol, "timeframe": timeframe})
        except Exception:
            pass

    return {"status": "ok", "decision": decision, "order": result}
