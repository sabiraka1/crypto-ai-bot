"""
Сценарий размещения торговых ордеров.
Обрабатывает создание market-ордеров с учетом размера позиции,
точности инструмента, идемпотентности и защитных выходов.
"""
from __future__ import annotations

import logging
import math
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
    """Получить текущее время в миллисекундах."""
    return int(time.time() * 1000)


def _last_price(broker: Any, symbol: str) -> float:
    """Получить последнюю цену инструмента."""
    t = broker.fetch_ticker(symbol)
    px = t.get("last") or t.get("close") or 0.0
    return float(px)


def _get_market_meta(broker: Any, symbol: str) -> Dict[str, Any]:
    """
    Получить метаданные рынка: точность, лимиты из ccxt.

    Args:
        broker: Брокер с доступом к рынкам
        symbol: Торговый символ

    Returns:
        Словарь с precision и limits, или дефолтные значения
    """
    try:
        ex = getattr(broker, "ccxt", None) or broker
        markets = getattr(ex, "markets", None)
        if markets and symbol in markets:
            m = markets[symbol]
            amt_prec = (m.get("precision") or {}).get("amount")
            px_prec = (m.get("precision") or {}).get("price")
            amt_min = (((m.get("limits") or {}).get("amount") or {}).get("min"))
            amt_max = (((m.get("limits") or {}).get("amount") or {}).get("max"))
            return {
                "amount_precision": int(amt_prec) if isinstance(amt_prec, (int,)) else None,
                "price_precision": int(px_prec) if isinstance(px_prec, (int,)) else None,
                "amount_min": float(amt_min) if amt_min is not None else None,
                "amount_max": float(amt_max) if amt_max is not None else None,
            }
    except Exception:
        pass
    return {"amount_precision": None, "price_precision": None, "amount_min": None, "amount_max": None}


def _is_spot(broker: Any, symbol: str) -> bool:
    """Проверка, что инструмент относится к spot (guard для long-only спота)."""
    try:
        ex = getattr(broker, "ccxt", None) or broker
        markets = getattr(ex, "markets", None)
        if markets and symbol in markets:
            m = markets[symbol] or {}
            if m.get("spot") is True:
                return True
            if (m.get("type") or "").lower() == "spot":
                return True
    except Exception:
        pass
    return False


def _quantize_amount(side: str, amount: float, amount_precision: Optional[int], amount_min: Optional[float]) -> float:
    """
    Квантование объема с учетом точности и минимальных требований.

    Args:
        side: Сторона сделки ("buy" | "sell")
        amount: Исходный объем
        amount_precision: Точность объема
        amount_min: Минимальный объем

    Returns:
        Скорректированный объем
    """
    # Применяем точность: для BUY режем вниз, для SELL — вверх
    if amount_precision is not None:
        q = Decimal("1") / (Decimal(10) ** int(amount_precision))
        dec = Decimal(str(amount))
        dec_q = dec.quantize(q, rounding=ROUND_DOWN if side == "buy" else ROUND_UP)
        amount = float(dec_q)

    # Проверяем минимальный объем
    if amount_min is not None and amount < amount_min:
        amount = amount_min if side == "buy" else 0.0

    # Не допускаем отрицательных значений
    return max(0.0, float(amount))


def _calc_amount_usd(cfg: Any, broker: Any, symbol: str) -> float:
    """
    Рассчитать объем в базовой валюте на основе бюджета в USD.

    Args:
        cfg: Конфигурация с POSITION_SIZE_USD
        broker: Брокер для получения цены
        symbol: Торговый символ

    Returns:
        Объем в базовой валюте
    """
    budget_usd = float(getattr(cfg, "POSITION_SIZE_USD", 0.0))
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
) -> Dict[str, Any]:
    """
    Единый сценарий исполнения ордера (market). Long-only стратегия.

    Args:
        cfg: Конфигурация торговли
        broker: Торговый брокер
        trades_repo: Репозиторий сделок
        positions_repo: Репозиторий позиций
        exits_repo: Репозиторий защитных выходов (опционально)
        symbol: Торговый символ
        side: Сторона сделки ('buy' | 'sell')
        idempotency_repo: Репозиторий идемпотентности (опционально)
        now_ms: Временная метка (опционально)

    Returns:
        Словарь с результатом исполнения:
        - accepted: bool - принят ли ордер
        - error: Optional[str] - ошибка (если есть)
        - executed_price/qty: float - цена и объем исполнения
        - idempotency_key: Optional[str] - ключ идемпотентности
    """
    ts = int(now_ms or _now_ms())
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))
    side = str(side or "buy").lower()

    # Валидация стороны сделки
    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "unsupported_side", "executed_price": 0.0, "executed_qty": 0.0}

    # ---- long-only spot guard ----
    if not _is_spot(broker, sym):
        return {"accepted": False, "error": "spot_only", "executed_price": 0.0, "executed_qty": 0.0}

    # Продажа допустима только при наличии long-позиции
    try:
        if side == "sell" and hasattr(positions_repo, "has_long") and not positions_repo.has_long(sym):
            return {"accepted": False, "error": "no_long_position", "executed_price": 0.0, "executed_qty": 0.0}
    except Exception as e:
        logger.debug("positions_repo.has_long failed: %r", e)

    # ---- идемпотентность: предотвращение дублирования ордеров ----
    idem_key = None
    if idempotency_repo is not None:
        try:
            bucket_ms = int(getattr(cfg, "IDEMPOTENCY_BUCKET_MS", 5_000))
            idem_key = build_key(symbol=sym, side=side, bucket_ms=bucket_ms, source="order")
            ok = idempotency_repo.check_and_store(
                idem_key, ttl_seconds=int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 300))
            )
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

    # ---- расчёт количества с учётом бюджета и точности рынка ----
    amt = _calc_amount_usd(cfg, broker, sym)
    m = _get_market_meta(broker, sym)
    amt = _quantize_amount(side, amt, m.get("amount_precision"), m.get("amount_min"))

    if amt <= 0.0:
        return {
            "accepted": False,
            "error": "zero_amount",
            "idempotency_key": idem_key,
            "executed_price": 0.0,
            "executed_qty": 0.0,
        }

    # ---- исполнение market-ордера (биржевая идемпотентность через clientOrderId/text) ----
    executed_price = 0.0
    executed_qty = 0.0
    try:
        params = {"clientOrderId": idem_key, "text": idem_key} if idem_key else {}
        od = broker.create_order(symbol=sym, type="market", side=side, amount=float(amt), price=None, params=params)
        executed_price = float(od.get("price") or _last_price(broker, sym) or 0.0)
        executed_qty = float(od.get("amount") or amt)
    except Exception as e:
        inc("orders_fail_total")
        logger.exception("broker.create_order failed: %s", e)
        return {
            "accepted": False,
            "error": "broker_error",
            "idempotency_key": idem_key,
            "executed_price": 0.0,
            "executed_qty": 0.0,
        }

    # ---- запись сделки в репозиторий (best-effort) ----
    try:
        payload = {
            "ts": ts,
            "symbol": sym,
            "side": side,
            "price": executed_price,
            "qty": executed_qty,
            "info": {"idempotency_key": idem_key},
        }
        if hasattr(trades_repo, "record"):
            trades_repo.record(payload)
        elif hasattr(trades_repo, "insert"):
            trades_repo.insert(payload)
        elif hasattr(trades_repo, "add"):
            trades_repo.add(payload)
    except Exception as e:
        logger.debug("trade persistence failed (non-fatal): %r", e)

    # ---- commit идемпотентности ----
    if idempotency_repo is not None and idem_key:
        try:
            idempotency_repo.commit(idem_key)
        except Exception as e:
            logger.debug("idempotency commit failed (non-fatal): %r", e)

    # ---- планирование защитных выходов (опционально) ----
    try:
        if exits_repo and hasattr(exits_repo, "schedule_for"):
            exits_repo.schedule_for(symbol=sym, side=side, entry_price=executed_price, qty=executed_qty, ts=ts)
    except Exception as e:
        logger.debug("protective exits scheduling failed (non-fatal): %r", e)

    # Успешное исполнение
    inc("orders_success_total")
    return {
        "accepted": True,
        "executed_price": executed_price,
        "executed_qty": executed_qty,
        "idempotency_key": idem_key,
    }
