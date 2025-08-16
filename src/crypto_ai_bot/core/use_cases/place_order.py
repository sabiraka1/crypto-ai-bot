from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe, to_exchange_symbol
from crypto_ai_bot.core.storage.repositories.interfaces import (
    IdempotencyRepository, TradeRepository, AuditRepository, PositionRepository
)
from crypto_ai_bot.utils import metrics


def _utc_minute_epoch(dt: Optional[datetime] = None) -> int:
    d = (dt or datetime.now(timezone.utc)).replace(second=0, microsecond=0, tzinfo=timezone.utc)
    return int(d.timestamp())


def _make_idem_key(decision: Dict[str, Any]) -> str:
    """
    Формат по спецификации:
      {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
    """
    symbol = str(decision.get("symbol","-"))
    side = str(decision.get("action","hold"))
    size = str(decision.get("size","0"))
    ts_min = _utc_minute_epoch()
    did = str(decision.get("id",""))[:8]
    return f"{symbol}:{side}:{size}:{ts_min}:{did}"


def place_order(
    cfg,
    broker,
    *,
    decision: Dict[str, Any],
    idem_repo: IdempotencyRepository,
    trades_repo: Optional[TradeRepository] = None,
    audit_repo: Optional[AuditRepository] = None,
    positions_repo: Optional[PositionRepository] = None,
) -> Dict[str, Any]:
    """
    Создание рыночного ордера по Decision. Все зависимости передаются снаружи.
    Никаких прямых импортов реализаций репозиториев.
    """
    # базовая валидация
    side = str(decision.get("action","hold"))
    if side not in ("buy","sell"):
        return {"status":"skip","reason":"non_trade_action"}

    symbol = normalize_symbol(str(decision.get("symbol") or getattr(cfg, "SYMBOL", "BTC/USDT")))
    timeframe = normalize_timeframe(str(decision.get("timeframe") or getattr(cfg, "TIMEFRAME", "1h")))
    size = Decimal(str(decision.get("size") or getattr(cfg, "DEFAULT_ORDER_SIZE", "0.01")))

    if not getattr(cfg, "ENABLE_TRADING", False):
        return {"status":"forbidden","reason":"trading_disabled"}

    key = _make_idem_key({**decision, "symbol": symbol})
    ttl = int(getattr(cfg, "IDEMPOTENCY_TTL_SECONDS", 300))

    # idempotency
    claimed, original = idem_repo.claim(key, payload=decision, ttl_seconds=ttl)
    if not claimed:
        # уже исполняли — вернём оригинал
        return {"status":"ok","idempotent":True,"original": original}

    # исполняем
    try:
        order = broker.create_order(symbol, "market", side, size, None)
        result = {"status":"ok","idempotent":False,"order":order}
        metrics.inc("order_submitted_total", {"side": side})

        # аудит/трейды — опционально
        if audit_repo is not None:
            audit_repo.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": "order_submitted",
                "symbol": symbol,
                "side": side,
                "size": str(size),
                "order_id": order.get("id"),
                "price": order.get("price"),
                "timeframe": timeframe,
                "decision_id": decision.get("id"),
            })
        if trades_repo is not None and order.get("status") == "closed":
            trades_repo.insert({
                "ts": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "side": side,
                "qty": str(size),
                "price": str(order.get("price")),
                "order_id": order.get("id"),
                "context": {"source":"place_order","decision_id": decision.get("id")},
            })

        idem_repo.commit(key, result)
        return result
    except Exception as e:
        metrics.inc("order_failed_total", {"reason": type(e).__name__})
        # освобождать ключ не обязательно — TTL защитит от шторма повторов
        return {"status":"error","error": f"{type(e).__name__}:{e}"}
