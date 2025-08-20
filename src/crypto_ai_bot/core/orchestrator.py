# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations
from typing import Any, Dict, Optional
import math
import logging

from crypto_ai_bot.utils.time import now_ms, monotonic_ms
from crypto_ai_bot.utils.metrics import record_slippage_bps, record_order_latency_ms, inc
from crypto_ai_bot.core.market_context import MarketContext  # ваш существующий
# ВАЖНО: clientOrderId/text НЕ генерим здесь — только idempotency_key
# Генерация clientOrderId происходит в brokers/ccxt_exchange.py

logger = logging.getLogger(__name__)

async def place_order(
    *,
    broker,
    positions_repo,
    trades_repo,
    symbol: str,
    side: str,                      # "buy" | "sell"
    notional: Optional[float],      # для BUY (в quote, напр. USDT)
    qty: Optional[float],           # для SELL (в base, напр. BTC)
    expected_price: float,          # для оценки slippage ex-ante
    fee_bps: float,
    idempotency_key: str,           # ключ для нашего репо + для gate text (передаётся в params)
    market_meta: Dict[str, Any],    # precision/limits
) -> Dict[str, Any]:
    t0 = monotonic_ms()

    if side == "buy":
        if notional is None or notional <= 0:
            raise ValueError("BUY requires positive notional")
        amount = float(notional)
    else:
        if qty is None or qty <= 0:
            raise ValueError("SELL requires positive qty")
        # округление количества по precision/limits (минимальные лоты)
        prec = int(market_meta.get("precision", {}).get("amount", 8))
        min_amt = float(market_meta.get("limits", {}).get("amount", {}).get("min", 0.0))
        amount = float(math.floor(qty * (10 ** prec)) / (10 ** prec))
        if amount < min_amt:
            return {"ok": False, "error": "amount_below_min", "min": min_amt}

    # отправляем ордер — clientOrderId/text сформирует брокер, здесь передаем только idempotency_key
    order = await broker.create_order(
        symbol=symbol,
        type="market",
        side=side,
        amount=amount,
        price=None,
        params={"idempotency_key": idempotency_key},
    )

    # метрики
    t1 = monotonic_ms()
    record_order_latency_ms(symbol, side, t1 - t0)

    # если есть executed price — посчитаем фактический slippage
    executed_price = float(order.get("average") or order.get("price") or 0.0)
    if executed_price > 0 and expected_price > 0:
        bps = abs(executed_price - expected_price) / expected_price * 10000.0
        record_slippage_bps(symbol, side, bps)

    inc("orders_placed_total", {"symbol": symbol, "side": side})
    return {"ok": True, "order": order}
