"""
Сценарий размещения торговых ордеров (spot, long-only).
— Идемпотентность приложения + биржевая (clientOrderId/text)
— Квантование объёма по precision/минимумам рынка
— Публикация событий в AsyncEventBus (DecisionEvaluated/OrderExecuted)
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, Optional, TypedDict, NotRequired

from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.utils.idempotency import build_key
from crypto_ai_bot.utils.metrics import inc

logger = logging.getLogger("use_cases.place_order")


class Order(TypedDict, total=False):
    """Структура торгового ордера."""
    id: str
    symbol: str
    side: str        # "buy" | "sell"
    qty: str
    price: float
    status: str      # "executed" | "rejected" | "failed"
    reason: NotRequired[str]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _last_price(broker: Any, symbol: str) -> float:
    t = broker.fetch_ticker(symbol)
    px = t.get("last") or t.get("close") or 0.0
    return float(px)


def _get_market_meta(broker: Any, symbol: str) -> Dict[str, Any]:
    """
    Возвращает precision/limits для символа из ccxt.markets, если доступны.
    {
      'amount_precision': Optional[int],
      'price_precision': Optional[int],
      'amount_min': Optional[float],
      'amount_max': Optional[float]
    }
    """
    try:
        ex = getattr(broker, "ccxt", None) or broker
        markets = getattr(ex, "markets", None)
        if markets and symbol in markets:
            m = markets[symbol] or {}
            prec = (m.get("precision") or {})
            lims = (m.get("limits") or {})
            amt_limits = lims.get("amount") or {}
            return {
                "amount_precision": prec.get("amount"),
                "price_precision": prec.get("price"),
                "amount_min": amt_limits.get("min"),
                "amount_max": amt_limits.get("max"),
            }
    except Exception:
        pass
    return {"amount_precision": None, "price_precision": None, "amount_min": None, "amount_max": None}


def _is_spot(broker: Any, symbol: str) -> bool:
    """Проверка, что инструмент — spot (guard для long-only)."""
    try:
        ex = getattr(broker, "ccxt", None) or broker
        markets = getattr(ex, "markets", None)
        if markets and symbol in markets:
            m = markets[symbol] or {}
            if m.get("spot") is True:
                return True
            if str(m.get("type") or "").lower() == "spot":
                return True
    except Exception:
        pass
    return False


def _quantize_amount(side: str, amount: float, amount_precision: Optional[int], amount_min: Optional[float]) -> float:
    """
    Квантование объёма: precision вниз для BUY, вверх для SELL; проверка минимумов.
    """
    out = float(amount or 0.0)
    if amount_precision is not None:
        q = Decimal(1).scaleb(-int(amount_precision))
        dec = Decimal(str(out))
        out = float(dec.quantize(q, rounding=ROUND_DOWN if side == "buy" else ROUND_UP))
    if amount_min is not None and out < float(amount_min or 0.0):
        out = float(amount_min) if side == "buy" else 0.0
    return max(0.0, out)


def _calc_amount_usd(cfg: Any, broker: Any, symbol: str) -> float:
    """Рассчитывает объём базовой валюты по бюджету в USD."""
    budget_usd = float(getattr(cfg, "POSITION_SIZE_USD", getattr(cfg, "POSITION_SIZE", 0.0)) or 0.0)
    if budget_usd <= 0:
        return 0.0
    px = _last_price(broker, symbol)
    if px <= 0:
        return 0.0
    return budget_usd / px


def place_order(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    exits_repo: Optional[Any],
    symbol: str,
    side: str,  # 'buy' | 'sell'
    idempotency_repo: Optional[Any] = None,
    now_ms: Optional[int] = None,
    bus: Optional[Any] = None,  # AsyncEventBus (опционально)
) -> Dict[str, Any]:
    """
    Единый сценарий исполнения market-ордера (spot, long-only).
    Возврат:
      {'accepted': bool, 'error': Optional[str], 'executed_price': float, 'executed_qty': float, 'idempotency_key': Optional[str]}
    """
    ts = int(now_ms or _now_ms())
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))
    side = str(side or "buy").lower()

    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "unsupported_side", "executed_price": 0.0, "executed_qty": 0.0}

    # --- spot-only guard ---
    if not _is_spot(broker, sym):
        return {"accepted": False, "error": "spot_only", "executed_price": 0.0, "executed_qty": 0.0}

    # Продажа допустима только при наличии long-позиции
    try:
        if side == "sell" and hasattr(positions_repo, "has_long") and not positions_repo.has_long(sym):
            return {"accepted": False, "error": "no_long_position", "executed_price": 0.0, "executed_qty": 0.0}
    except Exception as e:
        logger.debug("positions_repo.has_long failed: %r", e)

    # --- идемпотентность приложения ---
    idem_key = None
    if idempotency_repo is not None:
        try:
            bucket_ms = int(getattr(cfg, "IDEMPOTENCY_BUCKET_MS", 5_000))
            idem_key = build_key(symbol=sym, side=side, bucket_ms=bucket_ms, source="order")
            ok = idempotency_repo.check_and_store(idem_key, ttl_seconds=int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 300)))
            if not ok:
                inc("orders_duplicate_total")
                return {
                    "accepted": False,
                    "error": "duplicate_request",
                    "idempotency_key": idem_key,
                    "executed_price": 0.0,
                    "executed_qty": 0.0,
                }
        except Exception as e:
            logger.exception("idempotency claim failed: %s", e)

    # --- расчёт количества с учётом precision/минимумов ---
    amt = _calc_amount_usd(cfg, broker, sym)
    m = _get_market_meta(broker, sym)
    amt = _quantize_amount(side, amt, m.get("amount_precision"), m.get("amount_min"))
    if amt <= 0.0:
        return {"accepted": False, "error": "zero_amount", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}

    # --- исполнение market-ордера (биржевая идемпотентность: clientOrderId/text) ---
    executed_price = 0.0
    executed_qty = 0.0
    od: Dict[str, Any] = {}
    try:
        params = {"clientOrderId": idem_key, "text": idem_key} if idem_key else {}
        od = broker.create_order(symbol=sym, type="market", side=side, amount=float(amt), price=None, params=params)
        executed_price = float(od.get("price") or _last_price(broker, sym) or 0.0)
        executed_qty = float(od.get("amount") or amt)
    except Exception as e:
        inc("orders_fail_total")
        logger.exception("broker.create_order failed: %s", e)
        # событие об ошибке
        if bus is not None and hasattr(bus, "publish"):
            import asyncio
            asyncio.create_task(bus.publish({
                "type": "OrderExecuted",
                "symbol": sym,
                "order_id": "",
                "side": side,
                "qty": "0",
                "price": 0.0,
                "ts_ms": ts,
                "error": "broker_error",
            }))
        return {
            "accepted": False,
            "error": "broker_error",
            "idempotency_key": idem_key,
            "executed_price": 0.0,
            "executed_qty": 0.0,
        }

    # --- запись сделки в репозиторий (best-effort) ---
    try:
        payload = {
            "ts": ts,
            "symbol": sym,
            "side": side,
            "price": executed_price,
            "qty": executed_qty,
            "info": {"idempotency_key": idem_key, "exchange_order": od},
        }
        if hasattr(trades_repo, "record"):
            trades_repo.record(payload)
        elif hasattr(trades_repo, "insert"):
            trades_repo.insert(payload)
        elif hasattr(trades_repo, "add"):
            trades_repo.add(payload)
    except Exception as e:
        logger.debug("trade persistence failed (non-fatal): %r", e)

    # --- commit идемпотентности ---
    if idempotency_repo is not None and idem_key:
        try:
            idempotency_repo.commit(idem_key)
        except Exception as e:
            logger.debug("idempotency commit failed (non-fatal): %r", e)

    # --- планирование защитных выходов (опционально) ---
    try:
        if exits_repo and hasattr(exits_repo, "schedule_for"):
            exits_repo.schedule_for(symbol=sym, side=side, entry_price=executed_price, qty=executed_qty, ts=ts)
    except Exception as e:
        logger.debug("protective exits scheduling failed (non-fatal): %r", e)

    # --- событие об успешном исполнении ---
    inc("orders_success_total")
    if bus is not None and hasattr(bus, "publish"):
        import asyncio
        asyncio.create_task(bus.publish({
            "type": "OrderExecuted",
            "symbol": sym,
            "order_id": str(od.get("id") or ""),
            "side": side,
            "qty": str(executed_qty),
            "price": float(executed_price),
            "ts_ms": ts,
        }))

    return {
        "accepted": True,
        "executed_price": executed_price,
        "executed_qty": executed_qty,
        "idempotency_key": idem_key,
    }
