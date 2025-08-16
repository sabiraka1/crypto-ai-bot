from __future__ import annotations

import json
import math
from decimal import Decimal
from hashlib import sha256
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics

# ожидаем, что app.server передаёт сюда idempotency_repo, audit_repo, positions_repo и т.д.

def _short_decision_id(decision: Dict[str, Any]) -> str:
    """
    Детализация решения может быть большой; для короткого идентификатора берём устойчивые поля.
    """
    payload = {
        "action": decision.get("action"),
        "size": str(decision.get("size")),
        "sl": decision.get("sl"),
        "tp": decision.get("tp"),
        "trail": decision.get("trail"),
        "score": round(float(decision.get("score", 0.0)), 4) if decision.get("score") is not None else None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()[:8]

def _timestamp_minute_iso(ts: Optional[str] = None) -> str:
    """
    Возвращает отметку времени, округлённую до минуты, ISO UTC.
    Берём ts из decision.explain.context.ts, если есть; иначе now().
    """
    if ts:
        try:
            # допускаем уже ISO-строку
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return dt.isoformat()

def _build_idempotency_key(symbol: str, side: str, size: str, ts_minute_iso: str, decision_id8: str) -> str:
    return f"{symbol}:{side}:{size}:{ts_minute_iso}:{decision_id8}"

def place_order(cfg, broker, positions_repo, audit_repo, decision: Dict[str, Any], *, idempotency_repo=None) -> Dict[str, Any]:
    """
    Идемпотентное размещение ордера + минимальная запись в Аудит/Позиции.
    Контракт: возвращает словарь с полями order_ref (если исполнено) или duplicate_ref (если дубль).
    """
    symbol = decision.get("symbol", getattr(cfg, "SYMBOL", "BTC/USDT"))
    side = decision.get("action", "hold")
    if side not in ("buy", "sell"):
        return {"status": "no_action", "reason": f"action={side}"}

    size = str(decision.get("size", "0"))
    ts_from_decision = None
    try:
        ts_from_decision = (decision.get("explain") or {}).get("context", {}).get("ts")
    except Exception:
        ts_from_decision = None

    decision_id8 = _short_decision_id(decision)
    ts_minute = _timestamp_minute_iso(ts_from_decision)
    key = _build_idempotency_key(symbol, side, size, ts_minute, decision_id8)

    ttl = int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 600))
    payload_json = json.dumps({"symbol": symbol, "side": side, "size": size, "decision_id": decision_id8}, separators=(",", ":"), ensure_ascii=False)

    if idempotency_repo is not None:
        ok_new, existing_ref = idempotency_repo.check_and_store(key, ttl_sec=ttl, payload_json=payload_json)
        if not ok_new:
            # Дубликат — возвращаем исходный reference, если он есть
            return {"status": "duplicate", "idempotency_key": key, "duplicate_ref": existing_ref}

    # --- Размещаем ордер у брокера ---
    amount = Decimal(str(size))
    order_type = "market"
    price = None
    if amount <= 0:
        return {"status": "no_action", "reason": "size<=0"}

    try:
        order_ref = broker.create_order(symbol, order_type, side, amount, price)
        order_ref_json = json.dumps(order_ref, separators=(",", ":"), ensure_ascii=False)
        # commit идемпотентности
        if idempotency_repo is not None:
            idempotency_repo.commit(key, order_ref_json)
        metrics.inc("orders_submitted_total", {"side": side})
    except Exception as e:
        # не получилось – отпустим ключ, чтобы можно было повторить
        if idempotency_repo is not None:
            try:
                idempotency_repo.release(key)
            except Exception:
                pass
        metrics.inc("orders_failed_total", {"reason": type(e).__name__})
        raise

    # --- Аудит (best-effort) ---
    try:
        if audit_repo is not None and hasattr(audit_repo, "insert"):
            audit_repo.insert({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "order_submitted",
                "symbol": symbol,
                "side": side,
                "size": str(size),
                "order_ref": order_ref,
                "idempotency_key": key,
            })
    except Exception:
        pass

    # --- Позиции (best-effort, если есть контракт) ---
    try:
        if positions_repo is not None and hasattr(positions_repo, "upsert"):
            positions_repo.upsert({
                "symbol": symbol,
                "side": side,
                "size": str(size),
                "order_ref": order_ref,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception:
        pass

    return {"status": "submitted", "order_ref": order_ref, "idempotency_key": key}
