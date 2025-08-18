from decimal import Decimal
from typing import Dict, Any, Optional

from crypto_ai_bot.core.risk.sizing import compute_qty_for_notional, compute_qty_for_notional_market
from crypto_ai_bot.core.use_cases.protective_exits import ensure_protective_exits
from crypto_ai_bot.core.market_specs import quantize_amount


def place_order(*, cfg, broker, trades_repo, positions_repo, exits_repo, symbol: str, side: str) -> Dict[str, Any]:
    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "invalid side"}

    # Long-only guard
    if side == "sell" and not positions_repo.has_long(symbol):
        return {"accepted": False, "error": "long-only: no position to sell"}

    # Цена
    ticker = broker.fetch_ticker(symbol)
    last_price = float(ticker.get("last") or ticker.get("close") or ticker.get("info", {}).get("last", 0.0))
    if last_price <= 0:
        return {"accepted": False, "error": "no market price"}

    # --- market-aware сайзинг (если есть market-спеки у брокера) ---
    market = None
    if hasattr(broker, "get_market"):
        market = broker.get_market(symbol)

    if side == "buy":
        if market:
            qty, reason, need = compute_qty_for_notional_market(cfg, side=side, price=last_price, market=market)
            if qty <= 0:
                if reason == "min_amount":
                    return {"accepted": False, "error": "min_amount", "needed_amount": need}
                if reason == "min_notional":
                    return {"accepted": False, "error": "min_notional", "needed_notional": need}
                return {"accepted": False, "error": "qty=0"}
        else:
            qty = compute_qty_for_notional(cfg, side=side, price=last_price)
    else:
        # SELL: продаём весь остаток (с квантованием вниз, если знаем precision)
        qty = positions_repo.long_qty(symbol)
        if market:
            qty = quantize_amount(qty, market, side="sell")

    if qty <= 0:
        return {"accepted": False, "error": "qty=0"}

    enable_trading = bool(getattr(cfg, "ENABLE_TRADING", False))

    if enable_trading:
        order = broker.create_order(symbol=symbol, type="market", side=side, amount=qty)
        order_id = str(order.get("id"))
        trades_repo.create_pending_order(symbol=symbol, side=side, exp_price=last_price, qty=qty, order_id=order_id)
        if side == "buy":
            ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=symbol, entry_price=last_price, position_id=None)
        return {"accepted": True, "state": "pending", "order_id": order_id, "expected_price": last_price, "expected_qty": qty}

    else:
        order_id = f"paper-{symbol}-{int(Decimal(last_price) * 1000)}"
        trades_repo.create_pending_order(symbol=symbol, side=side, exp_price=last_price, qty=qty, order_id=order_id)
        fee_bps = float(getattr(cfg, "FEE_TAKER_BPS", 10)) / 10_000.0
        fee_amt = last_price * qty * fee_bps
        trades_repo.fill_order(order_id=order_id, executed_price=last_price, executed_qty=qty, fee_amt=fee_amt, fee_ccy="USDT")
        if side == "buy":
            ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=symbol, entry_price=last_price, position_id=None)
        return {"accepted": True, "state": "filled", "order_id": order_id, "executed_price": last_price, "executed_qty": qty, "fee_amt": fee_amt}
