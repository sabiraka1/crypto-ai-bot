from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.utils.metrics import inc, observe
from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.storage.uow import UnitOfWork


ORDER_RATE_PER_MINUTE = 10  # спецификация


def _make_idem_key(symbol: str, side: str, size: Decimal, decision_id: str | None = None) -> str:
    """
    {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
    """
    ts_minute = int(time.time() // 60)
    did = (decision_id or uuid.uuid4().hex)[:8]
    return f"{symbol}:{side}:{size}:{ts_minute}:{did}"


def place_order(cfg, broker: ExchangeInterface, uow: UnitOfWork, repos, decision: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()

    symbol = decision.get("symbol") or cfg.SYMBOL
    side = decision["action"]
    size = Decimal(str(decision["size"]))
    price = decision.get("price")

    key = _make_idem_key(symbol, side, size, decision.get("id"))
    payload = json.dumps({"decision": decision}, ensure_ascii=False)

    with uow as tx:
        idem_repo = repos.idempotency(tx)
        is_new, prev = idem_repo.check_and_store(key, payload, ttl_seconds=cfg.IDEMPOTENCY_TTL_SECONDS)
        if not is_new:
            inc("order_duplicate_total", {"symbol": symbol, "side": side})
            return {"status": "duplicate", "previous": prev}

        order = broker.create_order(symbol, "market", side, size, price)

        trades_repo = repos.trades(tx)
        positions_repo = repos.positions(tx)
        audit_repo = repos.audit(tx)

        audit_repo.append("order_submitted", {"symbol": symbol, "side": side, "size": str(size), "order": order})
        positions_repo.upsert_from_order(order)

        idem_repo.commit(key, result=json.dumps(order))
        tx.commit()

    latency = time.perf_counter() - t0
    observe("order_latency_seconds", latency, {"symbol": symbol, "side": side})
    if latency > getattr(cfg, "ORDER_BUDGET_SECONDS", 2.0):
        inc("performance_budget_exceeded_total", {"stage": "order"})
    inc("order_submitted_total", {"symbol": symbol, "side": side})
    return {"status": "ok", "order": order}
