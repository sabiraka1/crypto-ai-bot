# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.core.signals._fusion import build as build_features, decide as decide_policy
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.utils.rate_limit import MultiLimiter


def _decision_to_dict(decision: Any) -> Dict[str, Any]:
    # Поддерживаем dataclass Decision и словарь
    if hasattr(decision, "action"):
        return {"action": decision.action, "score": getattr(decision, "score", 0.0), "reason": getattr(decision, "reason", None)}
    return dict(decision or {})


def evaluate(
    *,
    cfg: Any,
    broker: Any,
    positions_repo: Any,
    symbol: Optional[str] = None,
    external: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    ЧИСТАЯ оценка без торговых операций.
    Возвращает {'decision': { 'action': 'buy|sell|hold', ...}, 'symbol': ... , 'features':..., 'context':... }
    """
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))
    feat = build_features(sym, cfg=cfg, broker=broker, positions_repo=positions_repo, external=external)
    decision = _decision_to_dict(decide_policy(feat.get("features", {}), feat.get("context", {})))
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
) -> Dict[str, Any]:
    """
    Оценка + (опционально) исполнение. Если action in {'buy','sell'} и лимитер пропускает — ставим market-ордер.
    """
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))

    feat = build_features(sym, cfg=cfg, broker=broker, positions_repo=positions_repo, external=external)
    decision = _decision_to_dict(decide_policy(feat.get("features", {}), feat.get("context", {})))
    action = (decision or {}).get("action")

    result: Dict[str, Any] = {"decision": decision, "symbol": sym}

    if action not in ("buy", "sell"):
        result["note"] = "hold"
        return result

    # rate limit перед исполнением
    if limiter is not None and not limiter.try_acquire("orders"):
        result["note"] = "rate_limited"
        result["executed"] = {"accepted": False, "error": "rate_limited"}
        return result

    executed = place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        symbol=sym,
        side=str(action),
        idempotency_repo=idempotency_repo,
    )
    result["executed"] = executed
    return result
