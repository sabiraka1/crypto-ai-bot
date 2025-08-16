# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.positions.manager import PositionManager
from crypto_ai_bot.core.storage.interfaces import (
    PositionRepository,
    TradeRepository,
    AuditRepository,
    UnitOfWork,
)


def _to_decimal(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def place_order(
    cfg: Any,
    broker: Any,  # оставляем для совместимости сигнатуры, внутри не используем
    *,
    positions_repo: PositionRepository,
    trades_repo: TradeRepository,
    audit_repo: AuditRepository,
    uow: UnitOfWork,
    decision: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Исполнение решения:
      - buy/sell: открытие или увеличение позиции (через PositionManager)
      - close: полное закрытие по символу
      - hold/unknown: пропуск

    Вся идемпотентность — на уровне вызывающего (use-case eval_and_execute).
    """
    symbol: str = decision.get("symbol") or getattr(cfg, "SYMBOL", "BTC/USDT")
    action: str = (decision.get("action") or "hold").lower()

    # hint-цена не обязательна; хранить как Decimal строкой
    price_hint: Optional[Decimal] = None
    if "price" in decision and decision["price"] is not None:
        price_hint = _to_decimal(decision["price"])

    size: Decimal = _to_decimal(decision.get("size", "0"))

    pm = PositionManager(
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        audit_repo=audit_repo,
        uow=uow,
    )

    if action in ("hold", "", None):
        return {"status": "skipped", "reason": "hold"}

    if action == "close":
        snap = pm.close_all(symbol)
        metrics.inc("order_submitted_total", {"side": "close"})
        return {"status": "ok", "position": snap}

    if action not in ("buy", "sell"):
        return {"status": "skipped", "reason": f"unknown action '{action}'"}

    signed_size = size if action == "buy" else (size * Decimal("-1"))

    # В PositionManager цена может быть None — возьмётся из брокера/текущего тикера, если реализовано.
    snap = pm.open_or_add(symbol, signed_size, price_hint)

    metrics.inc("order_submitted_total", {"side": action})
    return {"status": "ok", "position": snap}
