from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any, Tuple

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("risk.manager")


@dataclass
class RiskConfig:
    MAX_DAILY_LOSS_QUOTE: Decimal = dec("0")
    MAX_POSITION_BASE: Decimal = dec("0")
    MAX_DAILY_TURNOVER_QUOTE: Decimal = dec("0")

    @classmethod
    def from_settings(cls, s: Any) -> "RiskConfig":
        def dget(name: str, default: str = "0") -> Decimal:
            try:
                return dec(str(getattr(s, name, default) or default))
            except Exception:
                return dec(default)
        return cls(
            MAX_DAILY_LOSS_QUOTE=dget("RISK_DAILY_LOSS_LIMIT_QUOTE", "0"),
            MAX_POSITION_BASE=dget("RISK_MAX_POSITION_BASE", "0"),
            MAX_DAILY_TURNOVER_QUOTE=dget("RISK_MAX_DAILY_TURNOVER_QUOTE", "0"),
        )


class RiskManager:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self._storage: Optional[Any] = None
        self._settings: Optional[Any] = None

    def attach_storage(self, storage: Any) -> None:
        self._storage = storage

    def attach_settings(self, settings: Any) -> None:
        self._settings = settings

    def allow(self, *, symbol: str, action: str,
              quote_amount: Optional[Decimal], base_amount: Optional[Decimal]) -> Tuple[bool, str]:
        action = (action or "").lower().strip()
        if action not in ("buy", "sell", "hold"):
            return False, "unknown_action"
        if action == "hold":
            return True, ""

        # лимит позиции (base)
        try:
            if self.cfg.MAX_POSITION_BASE > 0 and action == "buy":
                pos = self._storage.positions.get_position(symbol) if self._storage else None
                cur_base = dec(str(getattr(pos, "base_qty", 0) or 0)) if pos else dec("0")
                if cur_base >= self.cfg.MAX_POSITION_BASE:
                    return False, "position_base_limit"
        except Exception:
            pass

        # дневной реализованный убыток (quote)
        try:
            if self.cfg.MAX_DAILY_LOSS_QUOTE > 0 and action == "buy":
                trades = getattr(self._storage, "trades", None)
                realized = None
                if trades and hasattr(trades, "realized_pnl_day_quote"):
                    try:
                        realized = trades.realized_pnl_day_quote(symbol)
                    except Exception:
                        realized = None
                if realized is not None and realized < (dec("0") - self.cfg.MAX_DAILY_LOSS_QUOTE):
                    return False, "max_daily_loss"
        except Exception:
            pass

        # дневной оборот (мягкий лимит)
        try:
            if self.cfg.MAX_DAILY_TURNOVER_QUOTE > 0 and action == "buy":
                trades = getattr(self._storage, "trades", None)
                if trades and hasattr(trades, "daily_turnover_quote"):
                    try:
                        t = trades.daily_turnover_quote(symbol)
                        if t >= self.cfg.MAX_DAILY_TURNOVER_QUOTE:
                            return False, "turnover_limit"
                    except Exception:
                        pass
        except Exception:
            pass

        return True, ""
