# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.metrics import inc, observe_histogram
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils import idempotency as idem

logger = get_logger(__name__)


def place_order(
    *,
    symbol: str,
    side: str,  # "buy" | "sell"
    settings: Any,
    broker: Any,
    repos: Any,
    bus: Any,
    notional_usd: Optional[Decimal] = None,   # для BUY (quote-amount)
    qty: Optional[Decimal] = None,            # для SELL (base-amount)
    expected_price: Optional[Decimal] = None, # для метрик/аудита
) -> dict:
    """
    Единая точка размещения ордеров.
    - Идемпотентность: reserve → create_order → commit (на успех).
    - ClientOrderId генерится внутри брокера (CCXTExchange), тут не дублируем.
    - Без асинхронщины: совместимо с вызывающим кодом evaluate_and_maybe_execute.
    """

    # --- базовые проверки аргументов ---
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "invalid_side"}

    if side == "buy" and (notional_usd is None or notional_usd <= 0):
        return {"ok": False, "error": "invalid_notional"}
    if side == "sell" and (qty is None or qty <= 0):
        return {"ok": False, "error": "invalid_qty"}

    idrepo = getattr(repos, "idempotency", None)
    trades_repo = getattr(repos, "trades", None)

    # --- идемпотентный ключ (временная корзина) ---
    bucket_ms = int(getattr(settings, "IDEMPOTENCY_BUCKET_MS", 15_000))
    t_ms = now_ms()
    key = idem.build_key(symbol=symbol, side=side, bucket_ms=bucket_ms, now_ms=t_ms)

    if idrepo is not None:
        reserved = False
        try:
            reserved = bool(idrepo.check_and_store(key))
        except Exception:
            logger.exception("idempotency.check_and_store failed")
            # осторожно: лучше заблокировать попытку, чем затопить биржу дублями
            return {"ok": False, "error": "idempotency_unavailable"}
        if not reserved:
            inc("orders_duplicate_total", {"symbol": symbol, "side": side})
            return {"ok": False, "error": "duplicate_request"}

    # --- подготовка параметров к брокеру ---
    amount = None
    if side == "buy":
        # для Gate/CCXT мы передаём quote notional; точный clientOrderId — внутри брокера
        amount = float(notional_usd)  # CCXT требует float
    else:
        amount = float(qty)

    try:
        # --- вызов биржи ---
        order = broker.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=amount,
            price=None,
            params=None,  # clientOrderId формируется в CCXTExchange
        )

        # --- запись в trades как pending (если ваша схема это требует) ---
        if trades_repo and hasattr(trades_repo, "create_pending_order"):
            try:
                trades_repo.create_pending_order(
                    order_id=order.get("id"),
                    client_order_id=order.get("clientOrderId") or order.get("text"),
                    symbol=symbol,
                    side=side,
                    qty=(float(qty) if qty is not None else 0.0),
                    expected_price=(float(expected_price) if expected_price is not None else None),
                    raw=order,
                )
            except Exception:
                logger.exception("trades_repo.create_pending_order failed")

        # --- коммит идемпотентности (КЛЮЧЕВОЕ ИЗМЕНЕНИЕ) ---
        if idrepo and hasattr(idrepo, "commit"):
            try:
                idrepo.commit(key, ref=order.get("id"))
            except Exception:
                # даже если commit не удался — ордер уже на бирже; логируем и живём дальше
                logger.exception("idempotency.commit failed")

        inc("orders_submitted_total", {"symbol": symbol, "side": side})
        if expected_price is not None and isinstance(expected_price, Decimal):
            try:
                exec_price = order.get("price") or order.get("average") or order.get("info", {}).get("price")
                if exec_price:
                    slippage_bps = abs(float(exec_price) - float(expected_price)) / float(expected_price) * 10000.0
                    observe_histogram("trade_slippage_bps", slippage_bps, {"symbol": symbol, "side": side})
            except Exception:
                logger.exception("slippage metric observe failed")

        return {"ok": True, "order": order}

    except Exception as e:
        logger.exception("create_order failed: %s", e)
        inc("orders_failed_total", {"symbol": symbol, "side": side})
        # Релизить бронь ключа не будем — TTL защитит от шторма дублей
        return {"ok": False, "error": "exchange_error", "detail": str(e)}
