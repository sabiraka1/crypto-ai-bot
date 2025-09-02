
from __future__ import annotations
from decimal import Decimal
from typing import Tuple

def dec(x: str) -> Decimal:
    return Decimal(x)

class PositionGuard:
    """Single source of truth for NO_SHORTS checks."""

    @staticmethod
    def can_sell(storage, symbol: str, amount: Decimal) -> Tuple[bool, Decimal]:
        """Return (allowed, max_sell_amount) respecting NO_SHORTS and held balance."""
        try:
            pos_repo = getattr(storage, "positions", None)
            if pos_repo is None:
                return False, dec("0")
            pos = pos_repo.get_position(symbol)
            held = getattr(pos, "base_qty", None) if pos else None
            if held is None:
                # try dict-like
                held = pos.get("base_qty") if isinstance(pos, dict) else None
            if held is None:
                held = dec("0")
            if held <= dec("0"):
                return False, dec("0")
            # Cap by held
            sell_amt = amount if amount is not None else held
            if sell_amt > held:
                sell_amt = held
            if sell_amt <= dec("0"):
                return False, dec("0")
            return True, sell_amt
        except Exception:
            return False, dec("0")
