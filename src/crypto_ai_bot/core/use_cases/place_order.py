# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

import hashlib
import json
import time
from contextlib import nullcontext
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.core.brokers.symbols import split_symbol
from crypto_ai_bot.core.types.trading import Trade  # DTO
from crypto_ai_bot.utils import metrics

# типовые интерфейсы; ожидаем, что они есть в core/storage/interfaces.py
try:
    from crypto_ai_bot.core.storage.interfaces import (
        IdempotencyRepository,
        TradeRepository,
        PositionRepository,
        AuditRepository,
        UnitOfWork,
    )
except Exception:
    # Мягкий fallback: объявим Protocol-подобные заглушки, чтобы не ронять импорт
    class IdempotencyRepository:  # type: ignore
        def claim(self, key: str, ttl_seconds: int) -> bool: ...
        def commit(self, key: str) -> None: ...
        def release(self, key: str) -> None: ...

    class TradeRepository:  # type: ignore
        def insert(self, trade: Trade) -> None: ...

    class PositionRepository:  # type: ignore
        def get_open_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]: ...
        def upsert(self, position: Dict[str, Any]) -> None: ...

    class AuditRepository:  # type: ignore
        def record(self, event: Dict[str, Any]) -> None: ...

    class UnitOfWork:  # type: ignore
        def transaction(self):
            return nullcontext()


def _decision_key(symbol: str, decision: Dict[str, Any]) -> str:
    """
    Дет-ключ идемпотентности. Если decision содержит 'idempotency_key' — используем его.
    Иначе хешируем существенные поля решения + символ.
    """
    explicit = decision.get("idempotency_key")
    if isinstance(explicit, str) and explicit:
        return explicit

    payload = {
        "symbol": symbol,
        "action": decision.get("action"),
        "size": str(decision.get("size")),
        "sl": decision.get("sl"),
        "tp": decision.get("tp"),
        "trail": decision.get("trail"),
        "score": round(float(decision.get("score") or 0.0), 4),
    }
    dj = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "order:" + hashlib.sha256(dj.encode("utf-8")).hexdigest()[:32]


def _amount_for_sell_fraction(
    broker: Any,
    positions_repo: PositionRepository,
    symbol: str,
    fraction: Decimal,
) -> Decimal:
    """
    Рассчитать объём продажи как долю от открытой позиции по символу.
    Если позиция неизвестна — попытка продать 0.
    """
    if fraction <= 0:
        return Decimal("0")

    # предпочтительно из репозитория позиций
    pos = None
    try:
        pos = positions_repo.get_open_by_symbol(symbol)  # ожидается dict или DTO
    except Exception:
        pos = None

    if not pos:
        return Decimal("0")

    qty = Decimal(str(pos.get("size") or pos.get("qty") or "0"))
    if qty <= 0:
        return Decimal("0")

    return (qty * fraction).quantize(Decimal("0.00000001"))


def place_order(
    cfg: Any,
    broker: Any,
    *,
    symbol: str,
    decision: Dict[str, Any],
    positions_repo: PositionRepository,
    trades_repo: TradeRepository,
    audit_repo: AuditRepository,
    idemp_repo: IdempotencyRepository,
    uow: Optional[UnitOfWork] = None,
) -> Dict[str, Any]:
    """
    Разместить ордер и записать последствия (trade/audit/position) атомарно.
    Все побочные эффекты — только внутри транзакции UnitOfWork (если передан).
    """
    if decision.get("action") in (None, "hold", "noop"):
        return {"ok": True, "skipped": True, "reason": "hold"}

    key = _decision_key(symbol, decision)
    ttl = int(getattr(cfg, "IDEMP_TTL_SEC", 30))

    if not idemp_repo.claim(key, ttl_seconds=ttl):
        metrics.inc("order_duplicate_total", {"symbol": symbol})
        return {"ok": True, "duplicate": True, "idempotency_key": key}

    # вычислим amount и сторону
    action = str(decision.get("action")).lower()
    side = "buy" if action == "buy" else "sell"
    size_raw = str(decision.get("size") or "0")
    amount = Decimal("0")

    if action == "buy":
        # size трактуем как абсолютное количество базовой валюты (см. policy._position_size_buy)
        amount = Decimal(size_raw)
    else:
        # size трактуем как долю (0..1) от открытой позиции
        try:
            frac = Decimal(size_raw)
        except Exception:
            frac = Decimal("0")
        amount = _amount_for_sell_fraction(broker, positions_repo, symbol, frac)

    if amount <= 0:
        idemp_repo.release(key)
        return {"ok": False, "error": "amount_is_zero", "idempotency_key": key}

    # client_order_id для брокера (детерминированный)
    client_oid = f"ai-{key}"

    # исполняем на брокере (market-ордер)
    metrics.inc("order_submitted_total", {"side": side})
    res = broker.create_order(symbol, "market", side, amount, None, client_order_id=client_oid)

    # собираем Trade DTO
    base, quote = split_symbol(symbol)
    trade = Trade(
        id=str(res.get("id") or ""),
        symbol=symbol,
        side=side,
        amount=Decimal(str(res.get("filled") or amount)),
        price=Decimal(str(res.get("price") or "0")),
        cost=Decimal(str(res.get("cost") or "0")),
        fee_currency=str(((res.get("fee") or {}) or {}).get("currency") or quote),
        fee_cost=Decimal(str(((res.get("fee") or {}) or {}).get("cost") or "0")),
        ts=int(res.get("timestamp") or int(time.time() * 1000)),
        client_order_id=client_oid,
        meta={"decision": decision, "raw": res},
    )

    # транзакционно записываем последствия
    ctx = uow.transaction() if (uow and hasattr(uow, "transaction")) else nullcontext()
    with ctx:
        audit_repo.record(
            {
                "type": "order_submitted",
                "symbol": symbol,
                "side": side,
                "amount": str(amount),
                "client_order_id": client_oid,
                "ts": trade.ts,
            }
        )
        trades_repo.insert(trade)

        # простейшая модель позиции: агрегируем по символу
        open_pos = positions_repo.get_open_by_symbol(symbol)
        if action == "buy":
            new_qty = Decimal(str((open_pos or {}).get("size", "0"))) + trade.amount
        else:
            new_qty = max(Decimal("0"), Decimal(str((open_pos or {}).get("size", "0"))) - trade.amount)

        positions_repo.upsert(
            {
                "symbol": symbol,
                "size": str(new_qty),
                "avg_price": str(trade.price),  # улучшение: пересчитывать среднюю
                "updated_ts": trade.ts,
            }
        )

        audit_repo.record(
            {
                "type": "order_filled",
                "symbol": symbol,
                "side": side,
                "amount": str(trade.amount),
                "price": str(trade.price),
                "fee": str(trade.fee_cost),
                "client_order_id": client_oid,
                "ts": trade.ts,
            }
        )

    idemp_repo.commit(key)
    metrics.inc("order_filled_total", {"side": side})
    return {"ok": True, "order": res, "trade_id": trade.id, "idempotency_key": key}
