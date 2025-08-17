from __future__ import annotations

import json
import math
import time
import hashlib
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.events import BusProtocol
from crypto_ai_bot.utils import metrics

# интерфейсы (типовые, не тянем конкретные реализации)
try:
    from crypto_ai_bot.core.storage.interfaces import (
        UnitOfWork,
        PositionsRepository as PositionsRepo,
        TradesRepository as TradesRepo,
        AuditRepository as AuditRepo,
    )
except Exception:  # pragma: no cover
    UnitOfWork = Any  # type: ignore
    PositionsRepo = Any  # type: ignore
    TradesRepo = Any  # type: ignore
    AuditRepo = Any  # type: ignore

from crypto_ai_bot.core.positions.manager import PositionManager

# Idempotency-репозиторий
try:
    from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository as IdemRepo
except Exception:  # pragma: no cover
    IdemRepo = None  # type: ignore

# опциональный декоратор лимитов
try:
    from crypto_ai_bot.utils.ratelimits import rate_limit
except Exception:  # pragma: no cover
    def rate_limit(*_, **__):  # type: ignore
        def _wrap(fn):
            return fn
        return _wrap


def _decision_side_size(decision: Dict[str, Any]) -> Tuple[str, Decimal]:
    action = str(decision.get("action", "hold"))
    raw_size = decision.get("size", "0")
    size = Decimal(str(raw_size))
    if action.lower() in ("buy", "long", "open_long"):
        return "buy", size
    if action.lower() in ("sell", "short", "close_long", "reduce"):
        return "sell", size
    return "hold", Decimal("0")


def _minute_bucket(ts_ms: Optional[int] = None) -> int:
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    return math.floor(ts_ms / 60000)


def _decision_id8(decision: Dict[str, Any]) -> str:
    # стабильный короткий id по содержимому решения
    h = hashlib.sha256(json.dumps(decision, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return h[:8]


def _mk_idem_key(symbol: str, side: str, size: Decimal, ts_minute: int, decision_id8: str) -> str:
    # СПЕЦИФИКАЦИЯ: {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
    return f"{symbol}:{side}:{size.normalize()}:{ts_minute}:{decision_id8}"


@rate_limit(limit=10, per=60)  # по спецификации: place_order ≤ 10/мин
def place_order(
    cfg: Settings,
    broker: Any,  # мягкий: можно передать None для unit-тестов
    positions_repo: PositionsRepo,
    trades_repo: TradesRepo,
    audit_repo: AuditRepo,
    uow: UnitOfWork,
    decision: Dict[str, Any],
    *,
    symbol: Optional[str] = None,
    bus: Optional[BusProtocol] = None,
    idem_repo: Optional[Any] = None,  # SqliteIdempotencyRepository
) -> Dict[str, Any]:
    """
    Конвейер исполнения:
      - формирует идемпотентный ключ;
      - защищается от дубликатов через idem_repo (если задан);
      - route: buy → open_or_add, sell → reduce_or_close, hold → no-op
      - пишет аудит/метрики; публикует события в шину (если задана).
    """
    sym = symbol or cfg.SYMBOL
    side, size = _decision_side_size(decision)

    # hold → ранний выход
    if side == "hold" or size <= 0:
        metrics.inc("order_skip_total", {"reason": "hold"})
        if bus:
            try:
                bus.publish({"type": "OrderSkipped", "reason": "hold", "symbol": sym})
            except Exception:
                pass
        return {"status": "skipped", "reason": "hold", "symbol": sym, "decision": decision}

    # idem key строго по спецификации
    ts_min = _minute_bucket()
    key = _mk_idem_key(sym, side, size, ts_min, _decision_id8(decision))

    # idempotency
    if idem_repo is not None and hasattr(idem_repo, "check_and_store"):
        is_new, prev = idem_repo.check_and_store(key, json.dumps(decision, default=str), ttl_seconds=cfg.IDEMPOTENCY_TTL_SEC)
        if not is_new:
            metrics.inc("order_duplicate_total", {"symbol": sym, "side": side})
            if bus:
                try:
                    bus.publish({"type": "OrderDuplicate", "symbol": sym, "side": side, "key": key})
                except Exception:
                    pass
            # отдать исходный результат (если он есть), иначе семантичный ответ
            return {"status": "duplicate", "symbol": sym, "side": side, "key": key, "original": prev or {}}

    t0 = time.perf_counter()

    # менеджер позиций — единая точка записи
    pm = PositionManager(
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        audit_repo=audit_repo,
        uow=uow,
    )

    # текущая «рыночная» цена (мягко: если брокера нет/падает — используем 0)
    price = Decimal("0")
    try:
        if broker is not None and hasattr(broker, "fetch_ticker"):
            tick = broker.fetch_ticker(sym)
            price = Decimal(str(tick.get("price", "0")))
    except Exception:
        pass

    # публикация планов
    if bus:
        try:
            bus.publish({"type": "OrderPlanned", "symbol": sym, "side": side, "size": str(size), "price": str(price)})
        except Exception:
            pass

    # исполнение (через PositionManager)
    if side == "buy":
        snap = pm.open_or_add(sym, size, price)
    else:  # side == "sell"
        snap = pm.reduce_or_close(sym, size, price)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    metrics.observe("latency_place_ms", latency_ms, {"symbol": sym, "side": side})
    metrics.inc("order_submitted_total", {"side": side})

    result = {
        "status": "executed",
        "symbol": sym,
        "side": side,
        "size": str(size),
        "price": str(price),
        "position_snapshot": snap or {},
        "latency_ms": latency_ms,
        "decision_id8": _decision_id8(decision),
        "idem_key": key if idem_repo is not None else None,
    }

    # сохраняем результат в idem (если есть)
    if idem_repo is not None and hasattr(idem_repo, "commit"):
        try:
            idem_repo.commit(key, json.dumps(result, default=str))
        except Exception:
            # не ломаем успешное исполнение
            pass

    # события
    if bus:
        try:
            bus.publish({"type": "OrderExecuted", **result})
        except Exception:
            pass

    return result
