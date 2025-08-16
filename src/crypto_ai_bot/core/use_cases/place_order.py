from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.utils.metrics import inc, observe
from crypto_ai_bot.core.types.trading import Order  # если нет — убери, это просто для type-hint


def place_order(cfg, broker, positions_repo, audit_repo, decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    Минимальная реализация размещения ордера с измерением performance budget.
    (Логика идемпотентности и UoW у тебя уже есть — здесь не трогаю)
    """
    t0 = time.perf_counter()
    side = decision.get("action")
    size = Decimal(str(decision.get("size", "0")))
    symbol = decision.get("explain", {}).get("context", {}).get("symbol", getattr(cfg, "SYMBOL", "BTC/USDT"))

    if side not in ("buy", "sell") or size == Decimal("0"):
        return {"status": "skipped", "reason": "hold_or_zero"}

    # простой market-ордер
    try:
        order = broker.create_order(symbol, "market", side, size, None)
        inc("order_submitted_total", {"side": side})
        result = {"status": "ok", "order": order}
    except Exception as exc:  # noqa: BLE001
        inc("order_failed_total", {"reason": exc.__class__.__name__})
        result = {"status": "error", "error": str(exc)}

    dur = time.perf_counter() - t0
    observe("order_duration_seconds", dur, {"symbol": symbol})
    if dur > float(getattr(cfg, "ORDER_BUDGET_SECONDS", 2.0)):
        inc("performance_budget_exceeded_total", {"stage": "order"})

    return result
