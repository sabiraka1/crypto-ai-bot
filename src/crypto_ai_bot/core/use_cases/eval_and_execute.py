from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from decimal import Decimal

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.positions.tracker import build_context
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import rate_limit

@rate_limit(
    calls=3, period=10.0,
    calls_attr="RL_EVAL_EXEC_CALLS", period_attr="RL_EVAL_EXEC_PERIOD",
    key_fn=lambda *a, **kw: f"eval_exec:{getattr(a[0],'MODE',None)}",
)
def eval_and_execute(cfg, broker, *, symbol: Optional[str]=None, timeframe: Optional[str]=None, limit: int=300, **repos) -> Dict[str, Any]:
    """
    Сквозной UC: evaluate -> risk -> place_order (идемпотентно).
    Возвращает словарь c ключами: status, risk, decision, order?.
    """
    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME

    # быстрый контекст для risk
    summary = build_context(cfg, broker, positions_repo=repos.get("positions_repo"), trades_repo=repos.get("trades_repo"))
    risk_ok, risk_reason = risk_manager.check(summary, cfg)

    # решение (индикаторы и т.д. внутри evaluate)
    decision = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit, **repos)

    result: Dict[str, Any] = {
        "symbol": sym,
        "timeframe": tf,
        "risk": {"ok": bool(risk_ok), "reason": risk_reason},
        "decision": decision,
    }

    # если риск заблокировал — не исполняем
    if not risk_ok:
        result["status"] = "blocked"
        return result

    action = (decision.get("action") or "hold").lower()
    if action not in ("buy", "sell"):
        result["status"] = "skipped"
        result["reason"] = "non_trade_action"
        return result

    # размер — из decision.size либо из конфигурации
    size = str(decision.get("size") or getattr(cfg, "DEFAULT_ORDER_SIZE", "0.0"))
    decision = {**decision, "size": size}

    # идемпотентная отправка
    order_res = place_order(cfg, broker,
                            positions_repo=repos.get("positions_repo"),
                            audit_repo=repos.get("audit_repo"),
                            idempotency_repo=repos.get("idempotency_repo"),
                            decision=decision)
    result["order"] = order_res
    result["status"] = order_res.get("status")
    return result
