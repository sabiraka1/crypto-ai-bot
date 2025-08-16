# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.core.brokers import ExchangeInterface
from crypto_ai_bot.core.storage.interfaces import (
    Repositories, StorageError, ConflictError, IdempotencyRepository,
)
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.utils import metrics  # если utils.metrics в другом месте, поправь импорт


IDEMPOTENCY_TTL_SECONDS_DEFAULT = 3600  # час защищаемся от повторов


def _make_idempotency_key(decision: Dict[str, Any]) -> str:
    """
    Строим стабильный ключ по значимым полям решения.
    Если ключ уже передан снаружи — используем его (не трогаем).
    """
    if "idempotency_key" in decision and decision["idempotency_key"]:
        return str(decision["idempotency_key"])

    # Список полей можно расширять — важна стабильность
    material = {
        "action": decision.get("action"),
        "symbol": normalize_symbol(decision.get("symbol")),
        "timeframe": normalize_timeframe(decision.get("timeframe")),
        "size": str(decision.get("size")),
        "sl": str(decision.get("sl")),
        "tp": str(decision.get("tp")),
        # Важно: не включаем волатильные цены времени, иначе ключ будет «всегда новый»
    }
    raw = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class PlaceOrderResult:
    status: str             # "ok" | "duplicate" | "error"
    idempotency_key: str
    order: Dict[str, Any] | None = None
    error: str | None = None


def place_order(
    cfg,
    broker: ExchangeInterface,
    repos: Repositories,
    decision: Dict[str, Any],
    *,
    idem_ttl_seconds: int = IDEMPOTENCY_TTL_SECONDS_DEFAULT,
) -> Dict[str, Any]:
    """
    Идемпотентное размещение ордера:
      1) Получает/строит idempotency_key;
      2) repos.idempotency.claim(key, ttl) — если False → duplicate;
      3) Пытается создать ордер у брокера и записать аудит/позиции;
      4) На успех — repos.idempotency.commit(key), на исключение — release(key).
    Возвращает dict (удобно для Telegram/HTTP-слоя).
    """
    action = str(decision.get("action") or "").lower()
    if action not in {"buy", "sell"}:
        return PlaceOrderResult(status="error", idempotency_key="n/a", error="Unsupported action").__dict__

    # нормализуем обязательные поля
    symbol = normalize_symbol(decision.get("symbol") or cfg.SYMBOL)
    timeframe = normalize_timeframe(decision.get("timeframe") or cfg.TIMEFRAME)

    size = decision.get("size")
    try:
        size = Decimal(str(size))
        if size <= 0:
            raise ValueError
    except Exception:
        return PlaceOrderResult(status="error", idempotency_key="n/a", error="Invalid size").__dict__

    # idempotency
    key = _make_idempotency_key({"action": action, "symbol": symbol, "timeframe": timeframe, "size": str(size),
                                 "sl": decision.get("sl"), "tp": decision.get("tp")})

    idem_repo: IdempotencyRepository = repos.idempotency
    claimed = idem_repo.claim(key, ttl_seconds=int(idem_ttl_seconds), payload={"symbol": symbol, "action": action})
    if not claimed:
        metrics.inc("order_duplicate_total", {"symbol": symbol, "action": action})
        return PlaceOrderResult(status="duplicate", idempotency_key=key, order=None).__dict__

    try:
        # создаём ордер у брокера
        order = broker.create_order(
            symbol=symbol,
            type_="market",  # можно сделать параметром в decision/cfg
            side=action,
            amount=size,
            price=None,
            idempotency_key=key,
            client_order_id=key[:20],  # многие биржи ограничивают длину
        )

        # журнал/аудит — адаптируй под свой контракт
        repos.audit.log_event("order_submitted", {
            "symbol": symbol,
            "action": action,
            "size": str(size),
            "order": order,
            "idem_key": key,
        })

        # при необходимости обнови позиции/трейды в твоих репозиториях

        idem_repo.commit(key)
        metrics.inc("order_submitted_total", {"symbol": symbol, "action": action})
        return PlaceOrderResult(status="ok", idempotency_key=key, order=order).__dict__

    except Exception as e:
        # очень важно: освободить ключ при неуспехе (иначе «залипнет» до TTL)
        try:
            idem_repo.release(key)
        finally:
            metrics.inc("order_failed_total", {"symbol": symbol, "action": action})
        return PlaceOrderResult(status="error", idempotency_key=key, error=str(e)).__dict__
