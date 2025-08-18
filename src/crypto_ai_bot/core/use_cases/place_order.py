# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import rate_limit, RateLimitExceeded
from crypto_ai_bot.core.positions.manager import PositionManager

# IDs
try:
    from crypto_ai_bot.utils.logging import get_correlation_id, get_request_id
except Exception:
    def get_correlation_id(): return None  # type: ignore
    def get_request_id(): return None      # type: ignore

log = logging.getLogger(__name__)


@rate_limit(max_calls=10, window=60)
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
    action = str(decision.get("action", "hold")).lower()
    side = action if action in ("buy", "sell") else "hold"
    size = Decimal(str(decision.get("size", "0")))
    if side == "hold" or size == Decimal("0"):
        metrics.inc("order_skip_total", {"reason": "hold"})
        return {"status": "skipped", "reason": "hold"}

    if idem_repo is not None:
        minute = int(int(decision.get("ts_ms", 0) or 0) // 60000)
        did = str(decision.get("id", ""))[:8]
        key = f"{symbol}:{side}:{size}:{minute}:{did}"
        is_new, prev = idem_repo.check_and_store(key, payload=str(decision))
        if not is_new and prev:
            metrics.inc("order_duplicate_total")
            return {"status": "duplicate", "prev": prev}

    pm = PositionManager(positions_repo=positions_repo, trades_repo=trades_repo, audit_repo=audit_repo, uow=uow)

    px = Decimal(str(broker.fetch_ticker(symbol).get("last", "0")))
    if px <= 0:
        return {"status": "error", "error": "invalid_price"}

    if side == "buy":
        snap = pm.open_or_add(symbol, size, px)
    elif side == "sell":
        snap = pm.reduce(symbol, size, px)
    else:
        return {"status": "error", "error": f"unknown_action:{action}"}

    if bus:
        evt = {
            "type": "OrderExecuted",
            "symbol": symbol,
            "timeframe": getattr(cfg, "TIMEFRAME", ""),
            "side": side,
            "qty": str(size),
            "price": str(px),
            "latency_ms": decision.get("latency_ms"),
            "request_id": get_request_id(),
            "correlation_id": get_correlation_id(),
        }
        try:
            bus.publish(evt)
        except Exception as e:
            log.warning("bus_publish_failed (OrderExecuted): %s", e)
            metrics.inc("bus_publish_errors_total")

    return {"status": "executed", "snapshot": snap}
