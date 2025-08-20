# src/crypto_ai_bot/core/use_cases/reconcile.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

logger = get_logger(__name__)


async def reconcile_open_orders(*, broker, trades_repo, symbol: str) -> Dict[str, Any]:
    """
    Единый reconcile: берет открытые ордера с биржи и обновляет локальное состояние.
    Приоритет сопоставления:
      1) clientOrderId / text
      2) exchange id
    Ничего не знает о БД кроме trades_repo.record_exchange_update/update_client_order_id.
    """
    try:
        open_orders: List[Dict[str, Any]] = await broker.fetch_open_orders(symbol=symbol)
    except Exception as e:
        logger.error("reconcile: fetch_open_orders failed", extra={"symbol": symbol, "error": str(e)})
        inc("reconcile_fetch_errors_total", {"symbol": symbol})
        return {"ok": False, "error": "fetch_failed"}

    updated = 0
    for od in open_orders:
        try:
            ex_id: Optional[str] = od.get("id") or od.get("orderId")
            coid: Optional[str] = od.get("clientOrderId") or od.get("text")

            if ex_id:
                trades_repo.record_exchange_update(order_id=ex_id, raw=od)
                if coid:
                    # зафиксируем связь для быстрого поиска в будущем
                    try:
                        trades_repo.update_client_order_id(order_id=ex_id, client_order_id=str(coid))
                    except Exception:
                        pass
                updated += 1
        except Exception as e:
            logger.warning("reconcile: update failed", extra={"symbol": symbol, "error": str(e)})

    inc("reconcile_updates_total", {"symbol": symbol})
    logger.info("reconcile: done", extra={"symbol": symbol, "updated": updated})
    return {"ok": True, "updated": updated}
