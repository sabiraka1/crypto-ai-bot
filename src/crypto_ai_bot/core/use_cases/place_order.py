# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, Optional

import asyncio

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.time import now_ms

logger = get_logger(__name__)


def _quantize(qty: Decimal, step: Decimal, *, mode: str) -> Decimal:
    if step <= 0:
        return qty
    rounding = ROUND_UP if mode == "sell" else ROUND_DOWN
    return (qty / step).to_integral_value(rounding=rounding) * step


async def _get_spread_bps(broker, symbol: str) -> float:
    t = await asyncio.to_thread(broker.fetch_ticker, symbol)
    bid = t.get("bid") or 0
    ask = t.get("ask") or 0
    if bid and ask and bid > 0:
        mid = (bid + ask) / 2.0
        return float((ask - bid) / mid * 10000.0)
    return 0.0


def _buy_quote_budget(notional_usd: float, fee_bps: float) -> float:
    # уменьшить бюджет на комиссию, чтобы маркет BUY прошёл у Gate
    fee = notional_usd * (fee_bps / 10000.0)
    return max(0.0, notional_usd - fee)


async def place_order(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    symbol: str,
    side: str,  # "buy" / "sell"
    notional_usd: Optional[float] = None,
    qty: Optional[Decimal] = None,  # для sell
    idempotency_repo: Any,
    idempotency_key: str,
    limiter: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Единая точка исполнения. CID генерирует брокер (ccxt_exchange), здесь только idempotency_key.
    """
    # 1) idempotency guard
    if not idempotency_repo.check_and_store(idempotency_key):
        inc("orders_duplicate_total", {"symbol": symbol, "side": side})
        return {"ok": False, "error": "duplicate_request"}

    # 2) spread/slippage guard
    max_spread_bps = float(getattr(cfg, "MAX_SPREAD_BPS", 50.0))
    slippage_bps = float(getattr(cfg, "SLIPPAGE_BPS", 20.0))
    spread_bps = await _get_spread_bps(broker, symbol)
    if spread_bps > max_spread_bps:
        inc("orders_spread_blocked_total", {"symbol": symbol, "side": side})
        return {"ok": False, "error": f"spread_too_wide:{spread_bps:.1f}bps"}

    # 3) получить market meta (precision/limits)
    meta = broker.get_market_meta(symbol)  # должен вернуть dict c step/min_amount
    amount_step = Decimal(str(meta.get("amount_step", "0")))
    min_amount = Decimal(str(meta.get("min_amount", "0")))

    # 4) исполнение
    order: Dict[str, Any]
    if side == "buy":
        if notional_usd is None or notional_usd <= 0:
            return {"ok": False, "error": "invalid_notional"}
        fee_bps = float(getattr(cfg, "FEE_BPS", 20.0))
        quote_cost = _buy_quote_budget(notional_usd, fee_bps)
        # лимитер по типу endpoint
        if limiter and not limiter.try_acquire("orders"):
            inc("orders_rate_limited_total", {"symbol": symbol, "side": side})
            return {"ok": False, "error": "rate_limited"}
        # брокер сам добавит clientOrderId (Gate.io text) и ретраи
        order = await asyncio.to_thread(
            broker.create_order,
            symbol=symbol,
            type="market",
            side="buy",
            amount=quote_cost,  # для Gate market BUY — сумма в quote
            params={},
        )
    elif side == "sell":
        if qty is None or qty <= 0:
            # возьмём текущую позицию из repo
            pos = positions_repo.get(symbol)
            if not pos or Decimal(str(pos.get("qty", "0"))) <= 0:
                return {"ok": False, "error": "no_long_position"}
            qty = Decimal(str(pos["qty"]))
        # округление под шаг
        qty = _quantize(Decimal(qty), amount_step, mode="sell")
        if qty <= 0 or (min_amount > 0 and qty < min_amount):
            return {"ok": False, "error": "too_small_qty"}
        if limiter and not limiter.try_acquire("orders"):
            inc("orders_rate_limited_total", {"symbol": symbol, "side": side})
            return {"ok": False, "error": "rate_limited"}
        order = await asyncio.to_thread(
            broker.create_order,
            symbol=symbol,
            type="market",
            side="sell",
            amount=float(qty),
            params={},
        )
    else:
        return {"ok": False, "error": "invalid_side"}

    # 5) запись pending/exec в trades_repo
    try:
        ex_id = order.get("id")
        coid = order.get("clientOrderId") or order.get("text")
        trades_repo.create_pending_order(
            order_id=ex_id,
            client_order_id=coid,
            symbol=symbol,
            side=side,
            requested_ts_ms=now_ms(),
            payload=order,
            slippage_bps=slippage_bps,
        )
    except Exception as e:
        # не критично для биржи, но важно для нашей учётки
        logger.warning("failed to record pending order", extra={"symbol": symbol, "error": str(e)})

    inc("orders_submitted_total", {"symbol": symbol, "side": side})
    return {"ok": True, "order": order}
