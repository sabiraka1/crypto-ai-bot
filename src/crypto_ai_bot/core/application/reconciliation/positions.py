from __future__ import annotations

from decimal import Decimal
from typing import Any, Tuple

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("application.reconcile.positions")


# --- Centralized NO_SHORTS helper ---------------------------------------------------------
def compute_sell_amount(storage: StoragePort, symbol: str, requested: Decimal | None) -> tuple[bool, Decimal]:
    """
    Centralized NO_SHORTS guard: cap sell amount by held base position.
    Returns (allowed, amount_to_sell). If nothing held -> (False, 0).
    The function is tolerant to both object- and dict-shaped position records.
    """
    try:
        repo = getattr(storage, "positions", None)
        if repo is None:
            return (False, dec("0"))
        pos = repo.get_position(symbol)
        # extract held base quantity
        held_raw: Any = None
        if pos is not None:
            held_raw = getattr(pos, "base_qty", None)
            if held_raw is None and isinstance(pos, dict):
                held_raw = pos.get("base_qty")
        held = dec(str(held_raw or "0"))
        if held <= dec("0"):
            return (False, dec("0"))
        # choose requested or full position
        amt = dec(str(requested)) if requested is not None else held
        if amt > held:
            amt = held
        if amt <= dec("0"):
            return (False, dec("0"))
        return (True, amt)
    except Exception:
        return (False, dec("0"))


# Backward-compat shim for old call-sites that expect PositionGuard.can_sell(...)
class PositionGuard:
    """Single source of truth for NO_SHORTS checks (compat wrapper)."""

    @staticmethod
    def can_sell(storage: StoragePort, symbol: str, amount: Decimal) -> Tuple[bool, Decimal]:
        return compute_sell_amount(storage, symbol, amount)


# --- Reconciliation logic (from original) -------------------------------------------------
async def reconcile_positions_batch(*, symbols: list[str], storage: StoragePort, broker: BrokerPort, bus: EventBusPort) -> None:
    """
    ĞŸÑ€Ğ¾ÑÑ‚Ğ°Ñ ÑĞ²ĞµÑ€ĞºĞ°: Ğ¿Ğ¾Ğ´Ñ‚ÑĞ³Ğ¸Ğ²Ğ°ĞµĞ¼ Ñ‚ĞµĞºÑƒÑ‰ÑƒÑ Ñ†ĞµĞ½Ñƒ Ğ¸ Ğ¾Ğ±Ğ½Ğ¾Ğ²Ğ»ÑĞµĞ¼ Ğ½ĞµÑ€ĞµĞ°Ğ»Ğ¸Ğ·Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ PnL.
    """
    for sym in symbols:
        try:
            t = await broker.fetch_ticker(sym)
            last = dec(str(t.get("last") or t.get("bid") or t.get("ask") or "0"))
            if last <= 0:
                continue
            pos = storage.positions.get_position(sym)
            if not pos:
                continue
            base = pos.base_qty or dec("0")
            if base <= 0:
                continue
            avg = pos.avg_entry_price or dec("0")
            if avg <= 0:
                continue
            unreal = (last - avg) * base
            # Ğ¾Ğ¿Ñ‚Ğ¸Ğ¼Ğ¸ÑÑ‚Ğ¸Ñ‡Ğ½Ğ¾Ğµ Ğ¾Ğ±Ğ½Ğ¾Ğ²Ğ»ĞµĞ½Ğ¸Ğµ
            storage.positions.apply_trade(
                symbol=sym, side="buy", base_amount=dec("0"), price=last, fee_quote=dec("0"), last_price=last
            )
            _log.debug("reconcile_ok", extra={"symbol": sym, "unrealized": str(unreal)})
        except Exception as exc:
            _log.warning("reconcile_error", extra={"symbol": sym, "error": str(exc)})


# Ğ¤ÑƒĞ½ĞºÑ†Ğ¸Ñ-Ğ¾Ğ±ĞµÑ€Ñ‚ĞºĞ° Ğ´Ğ»Ñ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸ Ñ orchestrator
async def reconcile_positions(symbol: str, storage: StoragePort, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
    """Ğ¤ÑƒĞ½ĞºÑ†Ğ¸Ñ-Ğ¾Ğ±ĞµÑ€Ñ‚ĞºĞ° Ğ´Ğ»Ñ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸ Ñ orchestrator."""
    await reconcile_positions_batch(
        symbols=[symbol],
        storage=storage,
        broker=broker,
        bus=bus
    )
