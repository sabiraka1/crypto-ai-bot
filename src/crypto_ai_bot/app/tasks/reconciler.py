def _exit_market(container, symbol: str, exit_row):
    # В long-only — продаём весь остаток по позиции (best-effort)
    pos_qty = container.positions_repo.long_qty(symbol)
    if pos_qty <= 0:
        container.exits_repo.deactivate(exit_row["id"])
        return

    qty = pos_qty
    if hasattr(container.broker, "get_market"):
        m = container.broker.get_market(symbol)
        if m:
            from crypto_ai_bot.core.market_specs import quantize_amount
            qty = quantize_amount(qty, m, side="sell")
            if qty <= 0:
                container.exits_repo.deactivate(exit_row["id"])
                return

    if not getattr(container.settings, "ENABLE_TRADING", False):
        container.exits_repo.deactivate(exit_row["id"])
        return

    try:
        container.broker.create_order(symbol=symbol, type="market", side="sell", amount=qty)
        container.exits_repo.deactivate(exit_row["id"])
    except Exception:
        # можно залогировать в аудит
        pass
