from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any, Tuple

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("risk.manager")


@dataclass
class RiskConfig:
    # мягкие лимиты: если метод в хранилище отсутствует — считаем лимит неприменимым
    MAX_DAILY_LOSS_QUOTE: Decimal = dec("0")   # если <0, блокируем новые buy при убытке ниже -X
    MAX_POSITION_BASE: Decimal = dec("0")      # хард лимит по размеру позиции (в базовой валюте)
    MAX_DAILY_TURNOVER_QUOTE: Decimal = dec("0")  # уже дублируется в budget_guard, оставляем как soft
    # можно расширять без ломающих последствий

    @classmethod
    def from_settings(cls, s: Any) -> "RiskConfig":
        def dget(name: str, default: str = "0") -> Decimal:
            try:
                return dec(str(getattr(s, name, default) or default))
            except Exception:
                return dec(default)
        return cls(
            MAX_DAILY_LOSS_QUOTE=dget("RISK_MAX_DAILY_LOSS_QUOTE", "0"),
            MAX_POSITION_BASE=dget("RISK_MAX_POSITION_BASE", "0"),
            MAX_DAILY_TURNOVER_QUOTE=dget("RISK_MAX_DAILY_TURNOVER_QUOTE", "0"),
        )


class RiskManager:
    """
    Domain-level риск-менеджер:
    - не импортирует application/infra;
    - использует duck-typing storage.trades.* если методы присутствуют;
    - если метод отсутствует — ограничение считается «неактивным».
    """
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self._storage: Optional[Any] = None
        self._settings: Optional[Any] = None

    def attach_storage(self, storage: Any) -> None:
        self._storage = storage

    def attach_settings(self, settings: Any) -> None:
        self._settings = settings

    # public API
    def allow(self, *, symbol: str, action: str,
              quote_amount: Optional[Decimal], base_amount: Optional[Decimal]) -> Tuple[bool, str]:
        action = (action or "").lower().strip()
        if action not in ("buy", "sell", "hold"):
            return False, "unknown_action"

        if action == "hold":
            return True, ""

        # лимит по позиции (base)
        try:
            if self.cfg.MAX_POSITION_BASE > 0 and action == "buy":
                pos = self._storage.positions.get_position(symbol) if self._storage else None
                cur_base = dec(str(getattr(pos, "base_qty", 0) or 0)) if pos else dec("0")
                add_base = dec("0")
                # очень грубо: если известна avg_entry_price — оценим base через quote/price,
                # но безопаснее блокировать по cur_base (не увеличивать выше MAX_POSITION_BASE).
                if cur_base >= self.cfg.MAX_POSITION_BASE:
                    return False, "position_base_limit"
        except Exception:
            pass

        # дневной PnL (quote)
        try:
            if self.cfg.MAX_DAILY_LOSS_QUOTE > 0 and action == "buy":
                # сначала пытаемся использовать realized pnl:
                trades = getattr(self._storage, "trades", None)
                realized = None
                if trades and hasattr(trades, "realized_pnl_day_quote"):
                    try:
                        realized = trades.realized_pnl_day_quote(symbol)
                    except Exception:
                        realized = None
                # если нет realized — берём общий дневной pnl:
                if realized is None and trades and hasattr(trades, "daily_pnl_quote"):
                    try:
                        realized = trades.daily_pnl_quote(symbol)
                    except Exception:
                        realized = None
                if realized is not None and realized < (dec("0") - self.cfg.MAX_DAILY_LOSS_QUOTE):
                    return False, "max_daily_loss"
        except Exception:
            pass

        # дневной оборот — мягкое правило (budget_guard уже блокирует жёстко)
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
