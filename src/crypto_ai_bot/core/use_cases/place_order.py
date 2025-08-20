# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.core._time import now_ms


Number = float  # лёгкий type alias для читабельности


def _spread_bps(ticker: Dict[str, Any]) -> float:
    bid = float(ticker.get("bid") or 0.0)
    ask = float(ticker.get("ask") or 0.0)
    if bid > 0 and ask > 0 and ask >= bid:
        mid = (ask + bid) / 2.0
        return ((ask - bid) / mid) * 10_000.0
    return 0.0


def _last_price(ticker: Dict[str, Any]) -> float:
    last = ticker.get("last")
    if last is None:
        bid = float(ticker.get("bid") or 0.0)
        ask = float(ticker.get("ask") or 0.0)
        if bid > 0.0 and ask > 0.0:
            return (bid + ask) / 2.0
        close = float(ticker.get("close") or 0.0)
        return max(close, bid, ask)
    return float(last)


def _effective_price(last_px: Number, slippage_bps: Number) -> float:
    return float(last_px) * (1.0 + float(slippage_bps) / 10_000.0)


def _quote_after_fee(notional_quote: Number, fee_bps: Number) -> float:
    """Сколько USDT реально можно пустить в маркет-бай с учётом комиссии."""
    fee = float(fee_bps) / 10_000.0
    return max(0.0, float(notional_quote) * (1.0 - fee))


def _positions_qty(positions_repo: Any, symbol: str) -> float:
    """Текущее количество базовой монеты по символу (если есть позиция)."""
    if positions_repo is None:
        return 0.0
    # форма 1: repo.get(symbol) -> {"qty": ...}
    if hasattr(positions_repo, "get"):
        row = positions_repo.get(symbol)
        if row:
            q = row.get("qty") or row.get("quantity")
            if q is not None:
                try:
                    return float(q)
                except Exception:
                    return 0.0
    # форма 2: repo.get_qty(symbol) -> float
    if hasattr(positions_repo, "get_qty"):
        try:
            return float(positions_repo.get_qty(symbol))
        except Exception:
            return 0.0
    return 0.0


def _make_idem_key(symbol: str, side: str, ttl_bucket_sec: int) -> str:
    """
    Строим идем-ключ на минутные (или иные) бакеты времени.
    Нужен ТОЛЬКО для приложения — биржевой clientOrderId генерит брокер.
    """
    bucket = int(now_ms() // 1000 // max(1, int(ttl_bucket_sec)))
    return f"order:{symbol}:{side}:{bucket}"


def place_order(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    exits_repo: Any,
    symbol: str,
    side: str,
    idempotency_repo: Any,
    bus: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Единая точка входа для исполнения рыночных сделок (long-only: BUY/SELL).

    ВАЖНО:
    - clientOrderId НЕ генерим здесь: этим занимается брокер (ccxt_exchange.py),
      чтобы соблюсти правила биржи (например, Gate.io text с 't-' и длиной).
    - Местная идемпотентность: предотвращаем повторы на уровне приложения,
      ключ сохраняем в repo с TTL. Ключ кладём в payload сделки для аудита.
    """
    side = side.lower().strip()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "bad_side", "side": side}

    # --- Настройки с разумными дефолтами
    fee_bps = float(getattr(cfg, "FEE_BPS", 20.0))  # 0.20%
    slippage_bps = float(getattr(cfg, "SLIPPAGE_BPS", 20.0))  # 0.20%
    max_spread_bps = float(getattr(cfg, "MAX_SPREAD_BPS", 50.0))  # 0.50%
    idem_ttl_sec = int(getattr(cfg, "ORDER_DEDUP_TTL_SEC", 60))
    notional_quote = float(getattr(cfg, "POSITION_SIZE_USD", 100.0))

    # --- Идемпотентность: локальная бронь
    idem_key = _make_idem_key(symbol, side, idem_ttl_sec)
    try:
        ok = idempotency_repo.check_and_store(idem_key, ttl_sec=idem_ttl_sec)
    except TypeError:
        # совместимость со старыми сигнатурами
        ok = idempotency_repo.check_and_store(idem_key, idem_ttl_sec)
    if not ok:
        return {"ok": False, "error": "duplicate_request", "idempotency_key": idem_key}

    # --- Рыночные данные и проверки
    try:
        tkr = broker.fetch_ticker(symbol) or {}
    except Exception as e:
        return {"ok": False, "error": "ticker_failed", "reason": str(e)}

    last_px = _last_price(tkr)
    if last_px <= 0:
        return {"ok": False, "error": "bad_last_price"}

    spread_bps = _spread_bps(tkr)
    if spread_bps > max_spread_bps:
        return {
            "ok": False,
            "error": "spread_too_wide",
            "spread_bps": spread_bps,
            "max_spread_bps": max_spread_bps,
        }

    eff_px = _effective_price(last_px, slippage_bps)

    # --- Подготовка параметров ордера
    try:
        market_meta = broker.get_market_meta(symbol)  # precision/limits если есть
    except Exception:
        market_meta = None

    order_payload: Dict[str, Any] = {
        "symbol": symbol,
        "type": "market",
        "side": side,
        # clientOrderId (Gate.io text) генерит брокер; здесь НЕ указываем.
        "params": {},
        "idempotency_key": idem_key,  # полезно для аудита и дальнейшего reconcile
        "expected_price": eff_px,
        "spread_bps": spread_bps,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
    }

    if side == "buy":
        # Gate.io market buy — передаём стоимость в котируемой валюте (USDT)
        quote_cost = _quote_after_fee(notional_quote, fee_bps)
        if quote_cost <= 0:
            return {"ok": False, "error": "bad_notional_after_fee"}

        order_payload["amount"] = quote_cost  # CCXT интерпретирует как "cost" на Gate
    else:
        # sell — продаём фактический объём позиции
        qty = _positions_qty(positions_repo, symbol)
        if qty <= 0:
            return {"ok": False, "error": "no_long_position"}
        order_payload["amount"] = qty

    # --- Вызов брокера
    try:
        od = broker.create_order(
            symbol=order_payload["symbol"],
            type=order_payload["type"],
            side=order_payload["side"],
            amount=order_payload["amount"],
            params=order_payload["params"],
        )
    except Exception as e:
        # если брокер провалился — дайте шанс повтору после TTL
        return {"ok": False, "error": "create_order_failed", "reason": str(e), "idempotency_key": idem_key}

    # --- Запись в репозиторий сделок (pending -> позже reconcile)
    order_id = od.get("id")
    try:
        trades_repo.create_pending_order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            expected_price=eff_px,
            idempotency_key=idem_key,
            raw=od,
        )
    except TypeError:
        # совместимость со старой сигнатурой
        trades_repo.create_pending_order(order_id, symbol, side, eff_px, idem_key, od)  # type: ignore

    # --- Публикуем событие (если есть шина)
    if bus is not None and hasattr(bus, "publish"):
        try:
            bus.publish(
                {
                    "kind": "order_submitted",
                    "symbol": symbol,
                    "side": side,
                    "expected_price": eff_px,
                    "idempotency_key": idem_key,
                    "exchange_order_id": order_id,
                }
            )
        except Exception:
            # события не критичны для потока исполнения
            pass

    return {
        "ok": True,
        "order": od,
        "idempotency_key": idem_key,
        "expected_price": eff_px,
        "spread_bps": spread_bps,
    }
