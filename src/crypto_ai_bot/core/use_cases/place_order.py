# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, Optional

from crypto_ai_bot.core._time import now_ms
from crypto_ai_bot.core.risk.manager import RiskManager
from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.utils.idempotency import make_order_key, quantize_bucket_ms
from crypto_ai_bot.utils.metrics import inc, observe_histogram
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)


def _quantize_amount(amount: float, precision: int, *, side: str) -> float:
    """
    Кол-во округляем в соответствии с требуемой точностью биржи.
    Для buy обычно указываем notional (у Gate/CCXT), для sell — количество BASE.
    """
    if precision < 0:
        precision = 0
    q = Decimal(str(amount)).quantize(
        Decimal("1." + "0" * precision),
        rounding=ROUND_DOWN if side == "buy" else ROUND_UP,
    )
    return float(q)


def _buy_quote_budget(notional: float, fee_bps: float) -> float:
    """
    Учитываем комиссию при рыночной покупке так, чтобы хватило средств.
    net = notional - fee(notional), где fee = notional * fee_bps/10000.
    """
    fee = notional * (fee_bps / 10000.0)
    net = max(0.0, notional - fee)
    return net


async def place_order(
    *,
    symbol: str,
    side: str,  # "buy" | "sell"
    notional_usd: float,
    settings,
    broker,
    trades_repo,
    positions_repo,
    idempotency_repo,
    market_meta_repo=None,
    risk_manager: Optional[RiskManager] = None,
) -> Dict[str, Any]:
    """
    ЕДИНАЯ точка входа для открытия/закрытия позиции по рынку (long-only).
    ВАЖНО:
      - idempotency-ключ строим здесь (приложение) через utils.idempotency
      - clientOrderId (Gate 'text') генерится ТОЛЬКО в брокере (ccxt_exchange.py)
      - время — единое now_ms() из core/_time.py
    """
    t0 = now_ms()
    symbol = str(symbol)

    # ---- Idempotency guard (минутный бакет) ---------------------------------
    bucket_ms = quantize_bucket_ms(t0, int(getattr(settings, "IDEMPOTENCY_BUCKET_MS", 60_000)))
    exchange_id = getattr(broker, "exchange_id", None)

    # нормализацию символа делаем в доменном слое (core), а utils остаётся "слепым"
    norm_symbol = normalize_symbol(exchange_id, symbol)

    idem_key = make_order_key(
        raw_symbol=norm_symbol,  # уже нормализованный символ
        side=side,
        bucket_ms=bucket_ms,
        exchange=exchange_id,
    )
    if not idempotency_repo.check_and_store(idem_key, ttl_ms=int(getattr(settings, "IDEMPOTENCY_TTL_MS", 120_000))):
        inc("orders_duplicate_total", {"symbol": norm_symbol, "side": side})
        return {"ok": False, "error": "duplicate_request", "idem_key": idem_key}

    # ---- Risk checks ---------------------------------------------------------
    if risk_manager is None:
        risk_manager = RiskManager(settings=settings, broker=broker, trades_repo=trades_repo, positions_repo=positions_repo)

    risk = await risk_manager.evaluate(symbol=norm_symbol, side=side, notional_usd=notional_usd)
    if not risk.get("ok", False):
        inc("orders_blocked_by_risk_total", {"symbol": norm_symbol, "side": side, "reason": risk.get("reason", "unknown")})
        return {"ok": False, "error": "risk_blocked", "risk": risk, "idem_key": idem_key}

    # ---- Market meta (precision/limits) -------------------------------------
    fee_bps = float(getattr(settings, "FEE_TAKER_BPS", 20.0))
    meta = None
    if market_meta_repo is not None:
        meta = market_meta_repo.get(norm_symbol)  # dict с precision/min_amount и т.п. (если есть)

    # ---- BUY: notional-based (Gate: quote amount) ----------------------------
    if side == "buy":
        quote_cost = _buy_quote_budget(notional_usd, fee_bps)
        # брокер сам позаботится о clientOrderId (Gate 'text') и rate limits
        ex_order = await broker.create_order(symbol=norm_symbol, type="market", side="buy", amount=quote_cost, params={})
        coid = ex_order.get("clientOrderId") or ex_order.get("text") or None
        order_id = ex_order.get("id") or ex_order.get("orderId") or "unknown"

        trades_repo.create_pending_order(symbol=norm_symbol, side="buy", exp_price=float(ex_order.get("price") or 0.0), qty=0.0, order_id=order_id)
        if coid:
            try:
                trades_repo.update_client_order_id(order_id=order_id, client_order_id=str(coid))
            except Exception:
                pass

        try:
            trades_repo.record_exchange_update(order_id=order_id, raw=ex_order)
        except Exception:
            pass

        dt_ms = now_ms() - t0
        observe_histogram("latency_order_submit_ms", float(dt_ms), {"symbol": norm_symbol, "side": "buy"})
        inc("orders_submitted_total", {"symbol": norm_symbol, "side": "buy"})
        return {"ok": True, "order": {"order_id": order_id, "client_order_id": coid}, "idem_key": idem_key}

    # ---- SELL: qty-based -----------------------------------------------------
    pos = positions_repo.get(norm_symbol)
    pos_qty = float(pos["qty"]) if pos else 0.0
    if pos_qty <= 0.0:
        return {"ok": False, "error": "no_long_position", "idem_key": idem_key}

    precision = int(meta.get("amount_precision", 6)) if meta else 6
    sell_qty = _quantize_amount(pos_qty, precision, side="sell")
    if sell_qty <= 0.0:
        return {"ok": False, "error": "min_amount_violation", "idem_key": idem_key}

    ex_order = await broker.create_order(symbol=norm_symbol, type="market", side="sell", amount=sell_qty, params={})
    coid = ex_order.get("clientOrderId") or ex_order.get("text") or None
    order_id = ex_order.get("id") or ex_order.get("orderId") or "unknown"

    trades_repo.create_pending_order(symbol=norm_symbol, side="sell", exp_price=float(ex_order.get("price") or 0.0), qty=sell_qty, order_id=order_id)
    if coid:
        try:
            trades_repo.update_client_order_id(order_id=order_id, client_order_id=str(coid))
        except Exception:
            pass
    try:
        trades_repo.record_exchange_update(order_id=order_id, raw=ex_order)
    except Exception:
        pass

    dt_ms = now_ms() - t0
    observe_histogram("latency_order_submit_ms", float(dt_ms), {"symbol": norm_symbol, "side": "sell"})
    inc("orders_submitted_total", {"symbol": norm_symbol, "side": "sell"})
    return {"ok": True, "order": {"order_id": order_id, "client_order_id": coid}, "idem_key": idem_key}
