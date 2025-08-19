from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.core.signals._fusion import build as build_features, decide as decide_policy
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.utils.rate_limit import MultiLimiter
try:
    from crypto_ai_bot.utils.metrics import inc
except Exception:
    def inc(*_args, **_kwargs):  # type: ignore
        pass


def _decision_to_dict(decision: Any) -> Dict[str, Any]:
    if hasattr(decision, "action"):
        return {
            "action": decision.action,
            "score": float(getattr(decision, "score", 0.0)),
            "reason": getattr(decision, "reason", None),
        }
    d = dict(decision or {})
    d["action"] = str(d.get("action", "hold")).lower()
    d["score"] = float(d.get("score", 0.0))
    return d


def _risk_eval(
    risk_manager: Any,
    *,
    decision: Dict[str, Any],
    context: Dict[str, Any],
    symbol: str,
    cfg: Any,
    broker: Any,
    positions_repo: Any,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Универсальная обёртка под разные сигнатуры RiskManager.
    Возвращает (allow, reason, maybe_updated_decision)
    """
    allow: bool = True
    reason: Optional[str] = None
    updated = decision

    try:
        # Пробуем наиболее информативную сигнатуру
        if hasattr(risk_manager, "evaluate"):
            out = risk_manager.evaluate(  # type: ignore[call-arg]
                decision=decision, context=context, symbol=symbol, cfg=cfg, broker=broker, positions_repo=positions_repo
            )
        elif callable(risk_manager):
            out = risk_manager(decision=decision, context=context, symbol=symbol, cfg=cfg, broker=broker, positions_repo=positions_repo)  # type: ignore[call-arg]
        else:
            out = True

        if isinstance(out, dict):
            allow = bool(out.get("allow", out.get("approved", True)))
            reason = out.get("reason")
            updated = out.get("decision", decision)
        elif isinstance(out, tuple):
            allow = bool(out[0])
            reason = out[1] if len(out) > 1 else None
            if len(out) > 2 and isinstance(out[2], dict):
                updated = out[2]
        else:
            allow = bool(out)
    except Exception as e:  # риски не должны валить пайплайн
        allow = True
        reason = f"risk_eval_error:{e!r}"

    return allow, reason, updated


def evaluate(
    *,
    cfg: Any,
    broker: Any,
    positions_repo: Any,
    symbol: Optional[str] = None,
    external: Optional[Dict[str, Any]] = None,
    bus: Optional[Any] = None,
) -> Dict[str, Any]:
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))
    feat = build_features(sym, cfg=cfg, broker=broker, positions_repo=positions_repo, external=external)
    decision = _decision_to_dict(decide_policy(feat.get("features", {}), feat.get("context", {})))

    if bus is not None and hasattr(bus, "publish"):
        import asyncio
        asyncio.create_task(bus.publish({
            "type": "DecisionEvaluated",
            "symbol": sym,
            "ts_ms": feat.get("context", {}).get("now_ms"),
            "decision": decision,
            "payload": {"features": feat.get("features", {}), "context": feat.get("context", {})},
        }))

    return {"decision": decision, "symbol": sym, "features": feat.get("features"), "context": feat.get("context")}


def evaluate_and_maybe_execute(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    exits_repo: Any,
    idempotency_repo: Optional[Any],
    limiter: Optional[MultiLimiter],
    symbol: Optional[str] = None,
    external: Optional[Dict[str, Any]] = None,
    bus: Optional[Any] = None,
    risk_manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Оценка + (опционально) исполнение:
      1) fuse/build → decide
      2) (опц.) risk_manager.evaluate → allow/deny
      3) rate limit
      4) place_order
    """
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))

    feat = build_features(sym, cfg=cfg, broker=broker, positions_repo=positions_repo, external=external)
    decision = _decision_to_dict(decide_policy(feat.get("features", {}), feat.get("context", {})))
    action = (decision or {}).get("action")

    result: Dict[str, Any] = {"decision": decision, "symbol": sym}

    if bus is not None and hasattr(bus, "publish"):
        import asyncio
        asyncio.create_task(bus.publish({
            "type": "DecisionEvaluated",
            "symbol": sym,
            "ts_ms": feat.get("context", {}).get("now_ms"),
            "decision": decision,
            "payload": {"features": feat.get("features", {}), "context": feat.get("context", {})},
        }))

    if action not in ("buy", "sell"):
        result["note"] = "hold"
        return result

    # ---- RiskManager (опционально) ----
    if risk_manager is not None:
        allow, reason, decision = _risk_eval(
            risk_manager,
            decision=decision,
            context=feat.get("context", {}),
            symbol=sym,
            cfg=cfg,
            broker=broker,
            positions_repo=positions_repo,
        )
        result["decision"] = decision  # на случай если риски модифицировали решение
        if not allow:
            inc("risk_block_total")
            result["note"] = "risk_blocked"
            result["executed"] = {"accepted": False, "error": "risk_blocked", "reason": reason or "blocked"}
            if bus is not None and hasattr(bus, "publish"):
                import asyncio
                asyncio.create_task(bus.publish({
                    "type": "RiskBlocked",
                    "symbol": sym,
                    "ts_ms": feat.get("context", {}).get("now_ms"),
                    "payload": {"reason": reason, "decision": decision},
                }))
            return result
        inc("risk_allow_total")

    # ---- Rate limit ----
    if limiter is not None and not limiter.try_acquire("orders"):
        result["note"] = "rate_limited"
        result["executed"] = {"accepted": False, "error": "rate_limited"}
        return result

    # ---- Execution ----
    executed = place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        symbol=sym,
        side=str(action),
        idempotency_repo=idempotency_repo,
        bus=bus,
    )
    result["executed"] = executed
    return result
