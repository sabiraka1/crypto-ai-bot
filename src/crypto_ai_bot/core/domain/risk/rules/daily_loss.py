from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class DailyLossConfig:
    limit_quote: Decimal = Decimal("0")  # 0 = disabled


class DailyLossRule:
    def __init__(self, cfg: DailyLossConfig) -> None:
        self.cfg = cfg

    def _pnl_today(self, trades_repo: Any, symbol: str) -> Decimal | None:
        """Get today's PnL from trades repository."""
        # Try fast paths first
        method_names = [
            "today_realized_pnl_quote",
            "pnl_today_quote",
            "realized_pnl_today",
            "daily_pnl_quote",
        ]
        for name in method_names:
            if hasattr(trades_repo, name):
                try:
                    method = getattr(trades_repo, name)
                    result = method(symbol)
                    return Decimal(str(result))
                except Exception:
                    continue
        # If no method available, return None
        return None

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        """Check if daily loss limit is exceeded."""
        lim = self.cfg.limit_quote
        if lim <= 0:
            return True, "disabled", {}

        val = self._pnl_today(trades_repo, symbol)
        if val is None:
            return True, "no_pnl_data", {}

        # Limit on LOSS: if pnl <= -limit -> block
        if val <= -lim:
            return False, "daily_loss_cap", {"pnl_today": str(val), "limit": str(lim)}

        return True, "ok", {}
