from decimal import Decimal
from typing import Dict, Any, Optional

from crypto_ai_bot.core.risk.sizing import compute_qty_for_notional, compute_qty_for_notional_market
from crypto_ai_bot.core.use_cases.protective_exits import ensure_protective_exits
from crypto_ai_bot.core.market_specs import quantize_amount
from crypto_ai_bot.core.brokers.symbols import to_ccxt_symbol, symbol_variants


def _long_qty_any(positions_repo, symbol: str) -> float:
    """
    Совместимость: ищем остаток позиции по нескольким представлениям символа.
    """
    qty = 0.0
    for s in symbol_variants(symbol):
        qty = max(qty, positions_repo.long_qty(s))
    return qty


def _has_long_any(positions_repo, symbol: str) -> bool:
    return _long_qty_any(positions_repo, symbol) > 0.0


def place_order(*, cfg, broker, trades_repo, positions_repo, exits_repo, symbol: str, side: str) -> Dict[str, Any]:
    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "invalid side"}

    # CCXT-совместимый символ для брокера
    sym_ccxt = to_ccxt_symbol(symbol, getattr(broker, "exchange_name", None))

    # Long-only guard (проверяем любые варианты старых символов)
    if side == "sell" and not _has_long_any(positions_repo, symbol):
        return {"accepted": False, "error": "long-only: no position to sell"}

    # Цена
    ticker = broker.fetch_ticker(sym_ccxt)
    last_price = float(ticker.get("last") or ticker.get("close") or ticker.get("info", {}).get("last", 0.0))
    if last_price <= 0:
        return {"accepted": False, "error": "no market price"}

    # --- market-aware сайзинг (если доступны маркет-спеки) ---
    market = broker.get_market(sym_ccxt) if hasattr(broker, "get_market") else None

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
        # SELL: продаём весь остаток (по символу из входа — совместимость с БД)
        qty = _long_qty_any(positions_repo, symbol)
        if market:
            qty = quantize_amount(qty, market, side="sell")

    if qty <= 0:
        return {"accepted": False, "error": "qty=0"}

    enable_trading = bool(getattr(cfg, "ENABLE_TRADING", False))

    if enable_trading:
        order = broker.create_order(symbol=sym_ccxt, type="market", side=side, amount=qty)
        order_id = str(order.get("id"))
        # В БД теперь пишем канон (CCXT-форму) — новые записи будут консистентны
        trades_repo.create_pending_order(symbol=sym_ccxt, side=side, exp_price=last_price, qty=qty, order_id=order_id)
        if side == "buy":
            ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=sym_ccxt, entry_price=last_price, position_id=None)
        return {"accepted": True, "state": "pending", "order_id": order_id, "expected_price": last_price, "expected_qty": qty}

    else:
        order_id = f"paper-{sym_ccxt}-{int(Decimal(last_price) * 1000)}"
        trades_repo.create_pending_order(symbol=sym_ccxt, side=side, exp_price=last_price, qty=qty, order_id=order_id)
        fee_bps = float(getattr(cfg, "FEE_TAKER_BPS", 10)) / 10_000.0
        fee_amt = last_price * qty * fee_bps
        trades_repo.fill_order(order_id=order_id, executed_price=last_price, executed_qty=qty, fee_amt=fee_amt, fee_ccy="USDT")
        if side == "buy":
            ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=sym_ccxt, entry_price=last_price, position_id=None)
        return {"accepted": True, "state": "filled", "order_id": order_id, "executed_price": last_price, "executed_qty": qty, "fee_amt": fee_amt}
