from __future__ import annotations

from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("application.reconcile.positions")


# --- Centralized NO_SHORTS helper ---
def compute_sell_amount(storage: StoragePort, symbol: str, requested: Decimal | None) -> tuple[bool, Decimal]:
    """
    Centralized NO_SHORTS guard: cap sell amount by held base position.
    Returns (allowed, amount_to_sell). If nothing held -> (False, 0).
    """
    try:
        repo = getattr(storage, "positions", None)
        if repo is None:
            return (False, dec("0"))

        pos = repo.get_position(symbol)

        # Extract held base quantity
        held_raw = None
        if pos is not None:
            held_raw = getattr(pos, "base_qty", None)
            if held_raw is None and isinstance(pos, dict):
                held_raw = pos.get("base_qty")

        held = dec(str(held_raw or "0"))
        if held <= dec("0"):
            return (False, dec("0"))

        # Choose requested or full position
        amt = dec(str(requested)) if requested is not None else held
        if amt > held:
            amt = held

        return (True, amt) if amt > dec("0") else (False, dec("0"))
    except Exception:
        return (False, dec("0"))


# Backward-compat shim
class PositionGuard:
    """Single source of truth for NO_SHORTS checks (compat wrapper)."""

    @staticmethod
    def can_sell(storage: StoragePort, symbol: str, amount: Decimal) -> tuple[bool, Decimal]:
        return compute_sell_amount(storage, symbol, amount)


# --- Reconciliation logic ---
async def reconcile_positions_batch(
    *, symbols: list[str], storage: StoragePort, broker: BrokerPort, bus: EventBusPort
) -> None:
    """Recompute unrealized PnL markers by refreshing last price."""
    for sym in symbols:
        try:
            ticker = await broker.fetch_ticker(sym)
            last = dec(str(ticker.get("last") or ticker.get("bid") or ticker.get("ask") or "0"))
            if last <= 0:
                continue

            pos = storage.positions.get_position(sym)
            if not pos:
                continue

            base = getattr(pos, "base_qty", dec("0")) or dec("0")
            if base <= 0:
                continue

            avg = getattr(pos, "avg_entry_price", dec("0")) or dec("0")
            if avg <= 0:
                continue

            unreal = (last - avg) * base

            # Touch local cache to persist last price for PnL calc
            storage.positions.apply_trade(
                symbol=sym, side="buy", base_amount=dec("0"), price=last, fee_quote=dec("0"), last_price=last
            )
            _log.debug("reconcile_ok", extra={"symbol": sym, "unrealized": str(unreal)})
        except Exception as exc:
            _log.warning("reconcile_error", extra={"symbol": sym, "error": str(exc)})


# Orchestrator wrapper
async def reconcile_positions(
    symbol: str, storage: StoragePort, broker: BrokerPort, bus: EventBusPort, _settings: Any
) -> None:
    """Orchestrator compatibility wrapper."""
    await reconcile_positions_batch(symbols=[symbol], storage=storage, broker=broker, bus=bus)
