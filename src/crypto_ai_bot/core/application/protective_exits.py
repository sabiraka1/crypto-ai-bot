from __future__ import annotations

async def protective_exits(*, symbol: str, storage, broker, bus, settings) -> None:
    """
    Close-only protective exits for LONG positions:
    - Stop Loss by percentage from avg_entry
    - Take Profit by percentage
    - Optional trailing stop (percentage)
    The function NEVER opens a short. It only places SELL up to current base_qty.
    """
    from crypto_ai_bot.utils.decimal import dec
    from crypto_ai_bot.utils.logging import get_logger

    log = get_logger("application.protective_exits")

    # Read thresholds from settings (0 disables)
    stop_pct = dec(str(getattr(settings, "EXITS_STOP_PCT", "0") or "0"))
    take_pct = dec(str(getattr(settings, "EXITS_TAKE_PCT", "0") or "0"))
    trail_pct = dec(str(getattr(settings, "EXITS_TRAIL_PCT", "0") or "0"))
    min_qty = dec(str(getattr(settings, "EXITS_MIN_BASE", "0") or "0"))

    try:
        pos = storage.positions.get_position(symbol)
    except Exception as e:
        log.error("position_fetch_failed", extra={"symbol": symbol, "error": str(e)})
        return

    if not pos:
        return

    base = pos.base_qty or dec("0")
    avg = pos.avg_entry_price or dec("0")
    if base <= 0 or avg <= 0:
        return

    # Fetch last price
    try:
        t = await broker.fetch_ticker(symbol)
        last = dec(str(t.get("last") or t.get("bid") or t.get("ask") or "0"))
    except Exception as e:
        log.warning("ticker_fetch_failed", extra={"symbol": symbol, "error": str(e)})
        return

    if last <= 0:
        return

    # Compute thresholds
    stop_price = avg * (dec("1") - (stop_pct / dec("100"))) if stop_pct > 0 else None
    take_price = avg * (dec("1") + (take_pct / dec("100"))) if take_pct > 0 else None

    # Trailing stop (optional) - keep the highest seen price if repo supports it
    trail_trigger = None
    if trail_pct > 0:
        try:
            max_seen = getattr(pos, "max_price", None)
            if max_seen is None or last > max_seen:
                max_seen = last
                if hasattr(storage.positions, "update_max_price"):
                    storage.positions.update_max_price(symbol, max_seen)
            trail_trigger = max_seen * (dec("1") - (trail_pct / dec("100")))
        except Exception:
            trail_trigger = last * (dec("1") - (trail_pct / dec("100")))

    should_close = False
    reason = ""

    if stop_price and last <= stop_price:
        should_close = True
        reason = f"stop_loss@{stop_pct}%"
    if not should_close and take_price and last >= take_price:
        should_close = True
        reason = f"take_profit@{take_pct}%"
    if not should_close and trail_trigger and last <= trail_trigger:
        should_close = True
        reason = f"trailing_stop@{trail_pct}%"

    if not should_close:
        return

    # SELL close-only up to base
    try:
        qty = base
        if min_qty > 0 and qty < min_qty:
            return
        order = await broker.create_market_sell(symbol=symbol, amount=qty)
        await bus.publish("trade.completed", {"symbol": symbol, "action": "sell", "reason": reason, "amount": str(qty)})
        log.info("protective_exit_sell", extra={"symbol": symbol, "qty": str(qty), "reason": reason})
    except Exception as e:
        await bus.publish("trade.failed", {"symbol": symbol, "action": "sell", "reason": str(e)})
        log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(e)})
