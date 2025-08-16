from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timezone
import json
import hashlib

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import rate_limit

def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)

def _decision_id(decision: Dict[str, Any]) -> str:
    """Стабильный идентификатор решения (если не задано явно)."""
    if "id" in decision and decision["id"]:
        return str(decision["id"])
    # иначе — хэш основного содержимого
    base = json.dumps(
        {
            "symbol": decision.get("symbol"),
            "timeframe": decision.get("timeframe"),
            "action": decision.get("action"),
            "size": decision.get("size"),
            "score": decision.get("score"),
        },
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]

def _build_idem_key(idem_repo: Any, *, symbol: str, side: str, size: str, decision_id: str, ts_ms: Optional[int]=None) -> str:
    """Если у репозитория есть build_key — используем спецификацию. Иначе — совместимый фоллбэк."""
    if hasattr(idem_repo, "build_key"):
        return idem_repo.build_key(symbol, side, size, decision_id, ts_ms=ts_ms)  # type: ignore[attr-defined]
    # fallback: {symbol}:{side}:{size}:{minute}:{id8}
    if ts_ms is None:
        ts_ms = _now_ms()
    minute = int(ts_ms // 60000)
    return f"{symbol}:{side}:{size}:{minute}:{(decision_id or '')[:8]}"

@rate_limit(
    calls=3, period=10.0,
    calls_attr="RL_PLACE_ORDER_CALLS", period_attr="RL_PLACE_ORDER_PERIOD",
    key_fn=lambda *a, **kw: f"place_order:{getattr(a[0],'MODE',None)}",
)
def place_order(cfg, broker, positions_repo, audit_repo, idempotency_repo, decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    Размещает ордер, используя идемпотентность:
      - строит key по спецификации;
      - check_and_store/claim — если дубль, возвращает original_order;
      - на успехе — commit(key, original_order).
    Ожидаемые поля decision: action ('buy'|'sell'|'hold'), size (str), symbol (str).
    """
    symbol = decision.get("symbol") or cfg.SYMBOL
    action = str(decision.get("action") or "hold").lower()
    size_s = str(decision.get("size") or "0")
    score = float(decision.get("score") or 0.0)

    if action not in ("buy", "sell"):
        return {"status": "skipped", "reason": "non_trade_action", "decision": decision}

    # key
    d_id = _decision_id(decision)
    key = _build_idem_key(idempotency_repo, symbol=symbol, side=action, size=size_s, decision_id=d_id)

    # попытка захвата идемпотентности
    payload = {"decision": decision, "ts_ms": _now_ms()}
    is_new = True
    stored_payload = None
    if hasattr(idempotency_repo, "check_and_store"):
        is_new, stored_payload = idempotency_repo.check_and_store(key, payload)  # type: ignore[attr-defined]
    elif hasattr(idempotency_repo, "claim"):
        is_new = bool(idempotency_repo.claim(key, payload))  # type: ignore[attr-defined]
    else:
        # нет репозитория — продолжаем без идемпотентности
        is_new = True

    if not is_new:
        orig = None
        if hasattr(idempotency_repo, "get_original_order"):
            try:
                orig = idempotency_repo.get_original_order(key)  # type: ignore[attr-defined]
            except Exception:
                orig = None
        metrics.inc("order_duplicate_total", {"symbol": symbol})
        return {"status": "duplicate", "key": key, "original_order": orig, "stored": stored_payload}

    # создаём ордер
    try:
        amount = Decimal(size_s)
    except Exception:
        return {"status": "error", "error": f"invalid_size:{size_s!r}"}

    try:
        order = broker.create_order(symbol=symbol, type_="market", side=action, amount=amount, price=None)
        metrics.inc("order_submitted_total", {"side": action})
    except Exception as e:
        metrics.inc("order_failed_total", {"reason": type(e).__name__})
        # отпуск ключа (опционально) — чтобы повторить позже
        try:
            if hasattr(idempotency_repo, "release"):
                idempotency_repo.release(key)  # type: ignore[attr-defined]
        except Exception:
            pass
        return {"status": "error", "error": f"broker_failed:{type(e).__name__}: {e}"}

    # фиксация идемпотентности
    try:
        if hasattr(idempotency_repo, "commit"):
            idempotency_repo.commit(key, original_order=order)  # type: ignore[attr-defined]
    except Exception:
        pass

    # запись в аудит (best-effort)
    try:
        if audit_repo is not None and hasattr(audit_repo, "insert"):
            audit_repo.insert(event_type="order_submitted", payload={"key": key, "symbol": symbol, "side": action, "size": size_s, "score": score, "order": order})
    except Exception:
        pass

    # простое обновление позиций (опционально)
    try:
        if positions_repo is not None and hasattr(positions_repo, "upsert"):
            pos = {"symbol": symbol, "side": action, "amount": float(amount), "entry_price": float(order.get("price") or 0.0), "status": "open"}
            positions_repo.upsert(pos)
    except Exception:
        pass

    return {"status": "submitted", "key": key, "order": order}
