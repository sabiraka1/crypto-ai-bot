# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.positions.manager import PositionManager
from crypto_ai_bot.core.storage.repositories import (
    TradeRepositorySQLite,
    PositionRepositorySQLite,
    SnapshotRepositorySQLite,
    AuditRepositorySQLite,
)
from crypto_ai_bot.utils import metrics


def _to_dec(x: Any, default: str = "0") -> Decimal:
    try:
        return x if isinstance(x, Decimal) else Decimal(str(x))
    except Exception:
        return Decimal(default)


def _client_oid(decision: Dict[str, Any]) -> str:
    # детерминированный не нужен — достаточно «уникального» для идемпотентности
    return f"bot-{uuid.uuid4().hex[:16]}"


def place_order(
    cfg,
    broker,
    con,
    decision: Dict[str, Any],
    *,
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Исполнить решение бота:
      - action: buy|sell|hold
      - size: Decimal|str|float (если нет — DEFAULT_ORDER_SIZE из Settings)
      - sl/tp/trail: опционально
    Все операции проводятся через PositionManager (он внутри пишет trade/position/audit в одной транзакции).
    """
    action = str(decision.get("action", "hold")).lower()
    if action == "hold":
        metrics.inc("order_skipped_total", {"reason": "hold"})
        return {"status": "skipped", "reason": "hold", "decision": decision}

    symbol = str(decision.get("symbol") or getattr(cfg, "SYMBOL", "BTC/USDT"))
    size = _to_dec(decision.get("size", getattr(cfg, "DEFAULT_ORDER_SIZE", "0")))
    if size <= 0:
        metrics.inc("order_skipped_total", {"reason": "size<=0"})
        return {"status": "skipped", "reason": "size<=0", "decision": decision}

    sl = decision.get("sl")
    tp = decision.get("tp")

    pm = PositionManager(
        con=con,
        broker=broker,
        trades=TradeRepositorySQLite(con),
        positions=PositionRepositorySQLite(con),
        audit=AuditRepositorySQLite(con),
    )

    client_order_id = client_order_id or decision.get("client_order_id") or _client_oid(decision)

    try:
        if action in {"buy", "sell"}:
            res = pm.open(
                symbol=symbol,
                side=action,
                size=size,
                sl=_to_dec(sl) if sl is not None else None,
                tp=_to_dec(tp) if tp is not None else None,
                client_order_id=client_order_id,
            )
            metrics.inc("order_submitted_total", {"side": action})
            return {"status": "filled", "result": res, "client_order_id": client_order_id}
        else:
            metrics.inc("order_skipped_total", {"reason": "unknown_action"})
            return {"status": "skipped", "reason": "unknown_action", "decision": decision}
    except Exception as e:
        metrics.inc("order_failed_total", {"reason": "exception"})
        return {"status": "error", "error": repr(e), "decision": decision}
