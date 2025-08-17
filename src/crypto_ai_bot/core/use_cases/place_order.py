# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics

try:
    from crypto_ai_bot.utils.rate_limit import rate_limit
except Exception:
    def rate_limit(*_, **__):
        def _wrap(fn):
            return fn
        return _wrap

from crypto_ai_bot.core.positions.manager import PositionManager


@rate_limit(limit=10, per=60)  # ≤ 10 исполнений/мин
def place_order(
    cfg: Settings,
    broker: Any,
    *,
    positions_repo: Any,
    trades_repo: Any,
    audit_repo: Any,
    uow: Any,
    decision: Dict[str, Any],
    symbol: str,
    bus: Optional[Any] = None,
    idem_repo: Optional[Any] = None,
) -> Dict[str, Any]:
    action = str(decision.get("action", "hold")).lower()  # buy|sell|hold
    side = action if action in ("buy", "sell") else "hold"
    size = Decimal(str(decision.get("size", "0")))
    if side == "hold" or size == Decimal("0"):
        metrics.inc("order_skip_total", {"reason": "hold"})
        return {"status": "skipped", "reason": "hold"}

    # идемпотентность (соответствие спецификации по ключу: symbol:side:size:minute:decision_id[:8])
    if idem_repo is not None:
        minute = int(int(decision.get("ts_ms", 0) or 0) // 60000)
        did = str(decision.get("id", ""))[:8]
        key = f"{symbol}:{side}:{size}:{minute}:{did}"
        is_new, prev = idem_repo.check_and_store(key, payload=str(decision))
        if not is_new and prev:
            metrics.inc("order_duplicate_total")
            return {"status": "duplicate", "prev": prev}

    pm = PositionManager(
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        audit_repo=audit_repo,
        uow=uow,
    )

    # цену берём у брокера
    px = Decimal(str(broker.fetch_ticker(symbol).get("last", "0")))
    if px <= 0:
        return {"status": "error", "error": "invalid_price"}

    if side == "buy":
        snap = pm.open_or_add(symbol, size, px)
    elif side == "sell":
        snap = pm.reduce_or_close(symbol, size, px)
    else:
        return {"status": "error", "error": f"unknown_action:{action}"}

    if bus:
        try:
            bus.publish({
                "type": "OrderExecuted",
                "symbol": symbol,
                "timeframe": getattr(cfg, "TIMEFRAME", ""),
                "side": side,                      # <-- важное выравнивание
                "qty": str(size),                  # <-- ожидание в bus_wiring
                "price": str(px),
                "latency_ms": decision.get("latency_ms"),
            })
        except Exception:
            pass

    return {"status": "executed", "snapshot": snap}
