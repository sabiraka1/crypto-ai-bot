from __future__ import annotations
from typing import Any, Dict, Optional
from decimal import Decimal

from crypto_ai_bot.core.storage.interfaces import (
    PositionRepository, TradeRepository, AuditRepository, UnitOfWork, IdempotencyRepository
)
from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.core.storage.repositories.idempotency import build_idempotency_key

def _dec(x: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(default)

def place_order(
    cfg,
    broker,
    *,
    positions_repo: Optional[PositionRepository] = None,
    trades_repo: Optional[TradeRepository] = None,
    audit_repo: Optional[AuditRepository] = None,
    uow: Optional[UnitOfWork] = None,
    idempotency_repo: Optional[IdempotencyRepository] = None,
    decision: Dict[str, Any],
) -> Dict[str, Any]:
    action = (decision.get("action") or "hold").lower()
    if action == "hold" or not cfg.ENABLE_TRADING:
        return {"status": "skipped", "reason": "no_execution", "decision": decision}

    side = "buy" if action == "buy" else ("sell" if action == "sell" else None)
    if side is None:
        return {"status": "skipped", "reason": "unknown_action", "decision": decision}

    symbol = normalize_symbol(decision.get("symbol") or cfg.SYMBOL)
    size = _dec(decision.get("size") or cfg.DEFAULT_ORDER_SIZE)
    if size <= 0:
        return {"status": "skipped", "reason": "zero_size", "decision": decision}

    decision_id = str(decision.get("id") or "")
    key = build_idempotency_key(symbol=symbol, side=side, size=str(size), decision_id=decision_id)
    if idempotency_repo is not None:
        prev = idempotency_repo.check_and_store(key, {"decision": decision})
        if prev is not None:
            return {"status": "duplicate", "original": prev}

    order = broker.create_order(symbol, "market", side, size, None) if broker else {"status": "no_broker"}

    if uow is not None:
        with uow:
            if audit_repo is not None:
                try:
                    audit_repo.append({"type": "audit.order_submitted", "symbol": symbol, "side": side, "size": str(size), "order": order})
                except Exception:
                    pass
            if positions_repo is not None:
                try:
                    positions_repo.upsert({"symbol": symbol, "qty": str(size if side=="buy" else -size), "avg_price": order.get("price")})
                except Exception:
                    pass
            if idempotency_repo is not None:
                try:
                    idempotency_repo.commit(key, {"order": order})
                except Exception:
                    pass
    else:
        if idempotency_repo is not None:
            try:
                idempotency_repo.commit(key, {"order": order})
            except Exception:
                pass

    return {"status": "submitted", "order": order}
