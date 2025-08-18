from decimal import Decimal
from typing import Dict, Any

from crypto_ai_bot.core.risk.sizing import compute_qty_for_notional
from crypto_ai_bot.core.use_cases.protective_exits import ensure_protective_exits


def place_order(*, cfg, broker, trades_repo, positions_repo, exits_repo, symbol: str, side: str) -> Dict[str, Any]:
    """
    Размещение ордера:
    - Long-only guard
    - Бумажный режим: создаём pending, затем сразу отмечаем filled (paper fill)
    - Live режим: создаём реальный ордер через CCXT → pending; дальше reconciler
    - Создание soft SL/TP записей (исполняет reconciler)
    - Совместимость с прежними ответами ('accepted', 'executed_*' для filled)
    """
    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "invalid side"}

    # Long-only: не позволяем 'sell' без открытой long-позиции
    if side == "sell" and not positions_repo.has_long(symbol):
        return {"accepted": False, "error": "long-only: no position to sell"}

    # Цена из тикера
    ticker = broker.fetch_ticker(symbol)
    last_price = float(ticker.get("last") or ticker.get("close") or ticker.get("info", {}).get("last", 0.0))
    if last_price <= 0:
        return {"accepted": False, "error": "no market price"}

    # Размер с учётом комиссии/проскальзывания
    qty = compute_qty_for_notional(cfg, side=side, price=last_price)
    if qty <= 0:
        return {"accepted": False, "error": "qty=0"}

    enable_trading = bool(getattr(cfg, "ENABLE_TRADING", False))

    if enable_trading:
        # Live: реальный рыночный ордер
        order = broker.create_order(symbol=symbol, type="market", side=side, amount=qty)
        order_id = str(order.get("id"))
        trades_repo.create_pending_order(symbol=symbol, side=side, exp_price=last_price, qty=qty, order_id=order_id)

        # Защитные выходы для входа в long
        if side == "buy":
            ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=symbol, entry_price=last_price, position_id=None)

        return {
            "accepted": True,
            "state": "pending",
            "order_id": order_id,
            "expected_price": last_price,
            "expected_qty": qty
        }

    else:
        # Paper: pending → немедленный fill (эмулируем исполнение)
        order_id = f"paper-{symbol}-{int(Decimal(last_price) * 1000)}"
        trades_repo.create_pending_order(symbol=symbol, side=side, exp_price=last_price, qty=qty, order_id=order_id)

        fee_bps = float(getattr(cfg, "FEE_TAKER_BPS", 10)) / 10_000.0  # 0.10% по умолчанию
        fee_amt = last_price * qty * fee_bps

        trades_repo.fill_order(
            order_id=order_id,
            executed_price=last_price,
            executed_qty=qty,
            fee_amt=fee_amt,
            fee_ccy="USDT"
        )

        if side == "buy":
            ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=symbol, entry_price=last_price, position_id=None)

        return {
            "accepted": True,
            "state": "filled",
            "order_id": order_id,
            "executed_price": last_price,
            "executed_qty": qty,
            "fee_amt": fee_amt
        }
