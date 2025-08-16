from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.positions import manager as positions_manager


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minute_epoch(ts: Optional[datetime] = None) -> int:
    dt = (ts or datetime.now(timezone.utc)).replace(second=0, microsecond=0, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _build_idem_key(symbol: str, side: str, size: str, decision: Dict[str, Any]) -> str:
    # Спецификация: {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
    ts_min = _minute_epoch()
    did = (decision.get("id") or decision.get("explain", {}).get("context", {}).get("id") or "")[:8]
    if not did:
        # fallback — короткий хэш от action+size+ts_min
        did = f"{abs(hash((decision.get('action'), size, ts_min)))%10_000_000:08d}"[:8]
    return f"{symbol}:{side}:{size}:{ts_min}:{did}"


def place_order(
    cfg,
    broker,
    *,
    decision: Dict[str, Any],
    idem_repo,
    trades_repo=None,
    audit_repo=None,
) -> Dict[str, Any]:
    """
    Размещает ордер и выполняет запись в репозитории позиций / аудита / сделок.
    Идемпотентность через idem_repo (claim -> duplicate | commit).

    Возвращает:
      { "status": "ok" | "duplicate" | "error", "order": {...}, "idempotency_key": str, "original": {...}? }
    """
    action = str(decision.get("action", "hold"))
    if action not in {"buy", "sell"}:
        return {"status": "skipped", "reason": "non_trade_action", "decision": decision}

    symbol = str(decision.get("symbol") or getattr(cfg, "SYMBOL", "BTC/USDT"))
    side = action
    size_str = str(decision.get("size", "0"))
    try:
        amount = Decimal(size_str)
    except Exception:
        amount = Decimal("0")

    if amount <= 0:
        return {"status": "skipped", "reason": "zero_size", "decision": decision}

    # Идемпотентность
    key = _build_idem_key(symbol, side, size_str, decision)
    claimed = False
    try:
        claimed = idem_repo.claim(key, ttl_s=int(getattr(cfg, "IDEMPOTENCY_TTL_S", 300)))
    except Exception as e:
        # если репозиторий недоступен — лучше перестраховаться и не отправлять ордер
        return {"status": "error", "error": f"idempotency_claim_failed:{type(e).__name__}"}

    if not claimed:
        # дубликат — вернуть оригинал, если есть
        original = None
        try:
            original = idem_repo.get_original_order(key)
        except Exception:
            original = None
        return {"status": "duplicate", "idempotency_key": key, "original": original}

    # Создать позицию на уровне менеджера (атомарность аудита обеспечивается там)
    pos = positions_manager.open(symbol=symbol, side=side, size=amount, sl=None, tp=None)

    # Отправка ордера в брокер
    order: Dict[str, Any]
    try:
        order = broker.create_order(symbol=symbol, type_="market", side=side, amount=amount)  # type: ignore[arg-type]
        metrics.inc("order_submitted_total", {"side": side})
    except Exception as e:
        metrics.inc("order_failed_total", {"reason": type(e).__name__})
        # освободить ключ, чтобы следующая попытка могла пройти
        try:
            idem_repo.release(key)
        except Exception:
            pass
        return {"status": "error", "error": f"broker_create_order_failed:{type(e).__name__}"}

    # Аудит
    evt = {
        "ts": _utcnow_iso(),
        "type": "order_submitted",
        "payload": {
            "symbol": symbol,
            "side": side,
            "size": size_str,
            "order": order,
            "position": pos,
            "decision": decision,
        },
    }
    try:
        if audit_repo is not None and hasattr(audit_repo, "append"):
            audit_repo.append(evt)
    except Exception:
        pass

    # Запись трейда (если что-то известно о цене)
    try:
        price = order.get("price") or order.get("avgPrice") or order.get("filledPrice")
        if price is None:
            # fallback: тикер
            try:
                t = broker.fetch_ticker(symbol)
                price = t.get("last") or t.get("close")
            except Exception:
                price = None
        if price is not None and trades_repo is not None and hasattr(trades_repo, "insert"):
            trades_repo.insert({
                "position_id": pos.get("id"),
                "symbol": symbol,
                "side": side,
                "size": size_str,
                "price": str(price),
                "fee": None,
                "ts": _utcnow_iso(),
                "payload": {"order": order},
            })
    except Exception:
        pass

    # Коммит идемпотентности (сохраняем оригинальный результат)
    try:
        idem_repo.commit(key, json.dumps({"order": order, "position": pos}).encode("utf-8"))
    except Exception:
        # ключ останется занятым до TTL — это безопаснее, чем повторно исполнять
        pass

    return {"status": "ok", "order": order, "position": pos, "idempotency_key": key}
