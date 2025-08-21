from __future__ import annotations
from typing import Any, Optional, Dict

from crypto_ai_bot.utils.ids import make_idempotency_key, make_client_order_id

async def place_order(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any | None,
    positions_repo: Any | None,
    exits_repo: Any | None,
    idempotency_repo: Any | None,
    limiter: Any | None,
    symbol: str,
    side: str,                   # "buy" | "sell"
    type: str = "market",        # "market" | "limit"
    amount: float = 0.0,
    price: Optional[float] = None,
    external: dict | None = None,
) -> Dict[str, any]:
    """
    Идемпотентная постановка ордера.
    Репозитории опциональны: если нет — пропускаем запись (не ломаемся).
    """
    ttl_sec = int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 60) or 60)
    key = make_idempotency_key(symbol, side.upper(), bucket_ms=ttl_sec * 1000)

    if idempotency_repo and hasattr(idempotency_repo, "exists"):
        try:
            if idempotency_repo.exists(key):
                return {"idempotent": True, "skipped": True, "key": key}
        except Exception:
            pass

    client_id = make_client_order_id(getattr(cfg, "EXCHANGE", "gateio"), key)

    order = await broker.create_order(symbol, side, type, amount, price, client_order_id=client_id)

    if idempotency_repo and hasattr(idempotency_repo, "save"):
        try:
            idempotency_repo.save(key, ttl_sec=ttl_sec)
        except Exception:
            pass
    if trades_repo and hasattr(trades_repo, "record_order"):
        try:
            trades_repo.record_order(order)
        except Exception:
            pass

    return {"idempotent": False, "skipped": False, "key": key, "order": order}
