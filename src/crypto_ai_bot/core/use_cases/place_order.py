# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.idempotency import build_key, validate_key
from crypto_ai_bot.utils.metrics import inc, observe_histogram

logger = logging.getLogger(__name__)


def place_order(
    *,
    broker,
    settings,
    trades_repo,
    positions_repo,
    idempotency_repo,
    symbol: str,
    side: str,                # "buy" | "sell"
    notional_usd: Optional[float] = None,  # для BUY
    sell_qty_base: Optional[float] = None, # для SELL
) -> Dict[str, Any]:
    """
    Синхронный use-case. clientOrderId генерируется внутри брокера (ccxt_exchange) — тут НЕ делаем.
    Idempotency: ключ резервируется ДО запроса в биржу, и коммитится после успешного исполнения.
    """
    ts_ms = now_ms()
    side = side.lower().strip()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "invalid_side"}

    # 1) Идемпотентный ключ (без завязки на core.*)
    bucket_ms = (ts_ms // 60_000) * 60_000  # минута
    idem_key = build_key("order", symbol, side, str(bucket_ms))
    if not validate_key(idem_key):
        return {"ok": False, "error": "bad_idempotency_key"}

    if not idempotency_repo.check_and_store(idem_key, ttl_ms=int(getattr(settings, "IDEMPOTENCY_TTL_MS", 120_000))):
        inc("orders_duplicate_total", {"symbol": symbol, "side": side})
        return {"ok": False, "error": "duplicate_request"}

    try:
        # 2) Размер / баланс / защита от продажи «в минус»
        if side == "sell":
            pos = positions_repo.get(symbol)
            pos_qty = float(pos["qty"]) if pos and "qty" in pos else 0.0
            if pos_qty <= 0.0:
                return {"ok": False, "error": "no_long_position"}
            qty = float(sell_qty_base or pos_qty)
            if qty <= 0.0:
                return {"ok": False, "error": "invalid_sell_qty"}
            # создаём ордер на продажу по рынку количеством base
            result = broker.create_market_sell(symbol=symbol, amount_base=qty)

        else:
            # BUY: тратим notional в котируемой валюте (с учётом комиссии брокер уже скорректирует/проверит)
            notional = float(notional_usd or 0.0)
            if notional <= 0.0:
                return {"ok": False, "error": "invalid_notional"}
            result = broker.create_market_buy(symbol=symbol, notional_quote=notional)

        # 3) Записываем сделку и фиксируем ключ
        trades_repo.record_exchange_update(
            order_id=result["id"],
            state=result.get("status") or "filled",
            raw=result,
        )
        idempotency_repo.commit(idem_key)

        # 4) Метрики
        exp = float(result.get("expected_price") or 0.0)
        got = float(result.get("average") or result.get("price") or 0.0)
        if exp > 0.0 and got > 0.0:
            slippage_bps = abs(got - exp) / exp * 10_000
            observe_histogram("trade_slippage_bps", slippage_bps, {"symbol": symbol, "side": side})

        inc("orders_success_total", {"symbol": symbol, "side": side})
        return {"ok": True, "order": result}

    except Exception as e:
        logger.exception("place_order failed: %s", e, extra={"symbol": symbol, "side": side})
        inc("orders_fail_total", {"symbol": symbol, "side": side})
        # ключ сам протухнет по TTL; намеренно не коммитим при ошибке
        return {"ok": False, "error": "exchange_error"}
