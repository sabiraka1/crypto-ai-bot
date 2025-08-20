# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations
from typing import Optional, Dict, Any
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import logging
from crypto_ai_bot.utils.idempotency import build_key, validate_key, now_ms
from crypto_ai_bot.utils.metrics import inc, observe_histogram

logger = logging.getLogger(__name__)

DEFAULT_FEE_BPS = 20  # 0.20% по умолчанию, можно перекрыть settings.FEE_BPS
DEFAULT_SLIPPAGE_BPS = 20

def _quote_budget_after_fee(notional: Decimal, fee_bps: int) -> Decimal:
    fee = (notional * Decimal(fee_bps) / Decimal(10000))
    out = notional - fee
    return out if out > 0 else Decimal("0")

def _quantize(amount: Decimal, step: Decimal, mode=ROUND_DOWN) -> Decimal:
    if step is None or step <= 0:
        return amount
    return (amount / step).to_integral_value(rounding=mode) * step

async def place_order(
    *,
    broker,
    trades_repo,
    positions_repo,
    idempotency_repo,
    settings,
    symbol: str,
    side: str,                  # "buy" | "sell"
    notional_usd: Optional[Decimal] = None,  # для buy (quote)
    qty_base: Optional[Decimal] = None,      # для sell (base)
    reason: Optional[str] = None,
    external: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Единая точка исполнения рыночных ордеров (long-only):
    - BUY: тратим notional (quote), уменьшаем на комиссию заранее
    - SELL: продаём текущую позицию (qty_base), квантуем вниз по шагу
    - Idempotency: резервируем ключ; после успеха — commit(key, order_id)
    - clientOrderId/text генерирует сам broker (ccxt_exchange) — тут НЕ дублируем
    """
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "invalid_side"}

    fee_bps = int(getattr(settings, "FEE_BPS", DEFAULT_FEE_BPS))
    slippage_bps = int(getattr(settings, "SLIPPAGE_BPS", DEFAULT_SLIPPAGE_BPS))
    bucket_ms = int(getattr(settings, "IDEMPOTENCY_BUCKET_MS", 60_000))

    # 1) Idempotency pre-check
    ikey = build_key(kind="order", symbol=symbol, side=side, bucket_ms=bucket_ms, extra={"ver": "1"})
    if not validate_key(ikey):
        return {"ok": False, "error": "bad_idempotency_key"}

    reserved, existing = idempotency_repo.check_and_store(ikey, ttl_ms=bucket_ms)
    if not reserved:
        inc("orders_duplicate_total", {"symbol": symbol, "side": side})
        return {"ok": False, "error": "duplicate_request", "key": ikey}

    try:
        market_meta = broker.get_market_meta(symbol)
        px = broker.fetch_last_price(symbol)
        if px <= 0:
            raise ValueError("bad_price")

        expected_px = Decimal(str(px)) * (Decimal(1) + Decimal(slippage_bps) / Decimal(10000))

        if side == "buy":
            if notional_usd is None or notional_usd <= 0:
                return {"ok": False, "error": "bad_notional"}
            budget = _quote_budget_after_fee(notional_usd, fee_bps)
            # для Gate/CCXT market BUY — amount это quote-сумма (USDT)
            amount_quote = budget.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            order = broker.create_order(
                symbol=symbol,
                type="market",
                side="buy",
                amount=float(amount_quote),          # quote amount для buy
                price=None,
                params={},                           # clientOrderId генерится внутри брокера
            )
        else:  # sell
            if qty_base is None:
                # по умолчанию продать весь актуальный объём позиции
                pos = positions_repo.get(symbol)
                if not pos or Decimal(str(pos.qty)) <= 0:
                    return {"ok": False, "error": "no_long_position"}
                qty_base = Decimal(str(pos.qty))

            step = market_meta.get("amount_step")
            q = _quantize(qty_base, Decimal(str(step)) if step else None, mode=ROUND_DOWN)
            if q <= 0:
                return {"ok": False, "error": "qty_too_small"}

            order = broker.create_order(
                symbol=symbol,
                type="market",
                side="sell",
                amount=float(q),  # base amount для sell
                price=None,
                params={},
            )

        # запись в трейды (pending->submitted)
        trades_repo.record_submitted(
            symbol=symbol,
            side=side,
            expected_price=float(expected_px),
            idempotency_key=ikey,
            exchange_order_id=order.get("id"),
            raw=order,
            reason=reason,
            external=external or {},
            ts_ms=now_ms(),
        )

        # ВАЖНО: коммитим идемпотентность на успех
        idempotency_repo.commit(ikey, ref_id=order.get("id"))

        observe_histogram(
            "order_expected_slippage_bps",
            float(slippage_bps),
            {"symbol": symbol, "side": side},
        )
        inc("orders_submitted_total", {"symbol": symbol, "side": side})
        return {"ok": True, "order_id": order.get("id")}

    except Exception as e:
        logger.exception("place_order failed: %s", e)
        inc("orders_failed_total", {"symbol": symbol, "side": side})
        # не коммитим — ключ истечёт по TTL и разрешит повтор
        return {"ok": False, "error": "exception", "message": str(e)}
