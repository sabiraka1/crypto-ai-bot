# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

from typing import Any, Dict, Optional

from .evaluate import evaluate
from .place_order import place_order
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils import metrics


def eval_and_execute(
    cfg: Any,
    broker: Any,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    repos: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Полный цикл: evaluate → (опц.) дополнительная верификация risk → place_order.
    repos = {
      "positions": PositionRepository,
      "trades": TradeRepository,
      "audit": AuditRepository,
      "idempotency": IdempotencyRepository,
      "uow": UnitOfWork (опционально),
    }
    """
    decision = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    # Доп. предохранитель: второй барьер риска (policy уже проверяет)
    ok, reason = risk_manager.check(
        {
            "indicators": {},  # уже учтены в policy; здесь достаточно рыночной части
            "market": {"price": decision.get("explain", {}).get("price", 0.0)},
        },
        cfg,
    )
    if not ok and decision.get("action") != "sell":
        # Разрешаем SELL даже при блоке (например, аварийное сокращение позиции)
        metrics.inc("eval_and_execute_blocked_total", {"reason": reason})
        return {"ok": True, "skipped": True, "reason": reason, "decision": decision}

    if decision.get("action") in (None, "hold", "noop"):
        return {"ok": True, "skipped": True, "reason": "hold", "decision": decision}

    out = place_order(
        cfg,
        broker,
        symbol=symbol,
        decision=decision,
        positions_repo=repos["positions"],
        trades_repo=repos["trades"],
        audit_repo=repos["audit"],
        idemp_repo=repos["idempotency"],
        uow=repos.get("uow"),
    )
    metrics.inc("eval_and_execute_total", {"action": decision.get("action", "unknown")})
    return {"decision": decision, "result": out}
