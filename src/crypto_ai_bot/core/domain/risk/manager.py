from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Tuple

# Domain-Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ° (Ñ‡Ğ¸ÑÑ‚Ñ‹Ğ¹ ÑĞ»Ğ¾Ğ¹)
from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakRule, LossStreakConfig
from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownRule, MaxDrawdownConfig

# Ğ”Ğ¾Ğ¿. Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ° (Ğ¼ÑĞ³ĞºĞ¾Ğµ Ğ¿Ğ¾Ğ´ĞºĞ»ÑÑ‡ĞµĞ½Ğ¸Ğµ)
try:
    from crypto_ai_bot.core.domain.risk.rules.max_orders_5m import MaxOrders5mRule, MaxOrders5mConfig
except Exception:
    MaxOrders5mRule = None  # type: ignore
    MaxOrders5mConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.max_turnover_5m import MaxTurnover5mRule, MaxTurnover5mConfig
except Exception:
    MaxTurnover5mRule = None  # type: ignore
    MaxTurnover5mConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.cooldown import CooldownRule, CooldownConfig
except Exception:
    CooldownRule = None  # type: ignore
    CooldownConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.spread_cap import SpreadCapRule, SpreadCapConfig
except Exception:
    SpreadCapRule = None  # type: ignore
    SpreadCapConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.daily_loss import DailyLossRule, DailyLossConfig
except Exception:
    DailyLossRule = None  # type: ignore
    DailyLossConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.correlation_manager import CorrelationManager, CorrelationConfig
except Exception:
    CorrelationManager = None  # type: ignore
    CorrelationConfig = None  # type: ignore

# utils Ğ² domain Ğ´Ğ¾Ğ¿ÑƒÑÑ‚Ğ¸Ğ¼Ñ‹
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("risk.manager")


@dataclass(frozen=True)
class RiskConfig:
    # Ğ±Ğ°Ğ·Ğ¾Ğ²Ñ‹Ğµ
    loss_streak_limit: int = 0
    max_drawdown_pct: float = 0.0
    max_orders_per_day: int = 0
    max_turnover_quote_per_day: Decimal = Decimal("0")

    # Ğ¼ÑĞ³ĞºĞ¸Ğµ Ğ»Ğ¸Ğ¼Ğ¸Ñ‚Ñ‹ (0 = Ğ²Ñ‹ĞºĞ»ÑÑ‡ĞµĞ½Ğ¾)
    max_orders_5m: int = 0
    max_turnover_5m_quote: Decimal = Decimal("0")
    cooldown_sec: int = 0
    max_spread_pct: float = 0.0
    daily_loss_limit_quote: Decimal = Decimal("0")

    # Ğ°Ğ½Ñ‚Ğ¸ĞºĞ¾Ñ€Ñ€ĞµĞ»ÑÑ†Ğ¸Ñ
    anti_corr_groups: list[list[str]] | None = None

    # Ğ¿Ñ€Ğ¾Ğ²Ğ°Ğ¹Ğ´ĞµÑ€ ÑĞ¿Ñ€ÑĞ´Ğ° (ĞµÑĞ»Ğ¸ None â€” SpreadCapRule Ğ¿Ñ€Ğ¾Ğ¿ÑƒÑĞºĞ°ĞµÑ‚ÑÑ)
    spread_provider: Optional[callable] = None

    @classmethod
    def from_settings(cls, s: Any, *, spread_provider: Optional[callable] = None) -> "RiskConfig":
        groups = getattr(s, "RISK_ANTI_CORR_GROUPS", None) or None
        if isinstance(groups, str):
            try:
                # "BTC/USDT|ETH/USDT;XRP/USDT|ADA/USDT"
                raw_groups = [g for g in groups.split(";") if g]
                groups = [g.split("|") for g in raw_groups]
            except Exception:
                groups = None

        from decimal import Decimal as D
        return cls(
            loss_streak_limit=int(getattr(s, "RISK_LOSS_STREAK_LIMIT", 0) or 0),
            max_drawdown_pct=float(getattr(s, "RISK_MAX_DRAWDOWN_PCT", 0.0) or 0.0),
            max_orders_per_day=int(getattr(s, "SAFETY_MAX_ORDERS_PER_DAY", 0) or 0),
            max_turnover_quote_per_day=D(str(getattr(s, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", 0.0) or 0.0)),
            max_orders_5m=int(getattr(s, "RISK_MAX_ORDERS_5M", 0) or 0),
            max_turnover_5m_quote=D(str(getattr(s, "RISK_MAX_TURNOVER_5M_QUOTE", 0.0) or 0.0)),
            cooldown_sec=int(getattr(s, "RISK_COOLDOWN_SEC", 0) or 0),
            max_spread_pct=float(getattr(s, "RISK_MAX_SPREAD_PCT", 0.0) or 0.0),
            daily_loss_limit_quote=D(str(getattr(s, "RISK_DAILY_LOSS_LIMIT_QUOTE", 0.0) or 0.0)),
            anti_corr_groups=groups,
            spread_provider=spread_provider,
        )


class RiskManager:
    """
    Ğ§Ğ¸ÑÑ‚Ñ‹Ğ¹ API Ğ´Ğ»Ñ application ÑĞ»Ğ¾Ñ:
    check(symbol, storage) -> (ok: bool, reason: str, extra: dict)
    ĞĞ¸ĞºĞ°ĞºĞ¸Ñ… Ğ¿ÑƒĞ±Ğ»Ğ¸ĞºĞ°Ñ†Ğ¸Ğ¹/ÑˆĞ¸Ğ½Ñ‹ Ğ²Ğ½ÑƒÑ‚Ñ€Ğ¸ domain.
    """

    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

        # Ğ±Ğ°Ğ·Ğ¾Ğ²Ñ‹Ğµ
        self._loss = LossStreakRule(LossStreakConfig(limit=cfg.loss_streak_limit))
        self._dd = MaxDrawdownRule(MaxDrawdownConfig(max_drawdown_pct=cfg.max_drawdown_pct))

        # Ğ´Ğ¾Ğ¿. Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ°
        self._orders5 = MaxOrders5mRule(MaxOrders5mConfig(limit=cfg.max_orders_5m)) if (MaxOrders5mRule and cfg.max_orders_5m > 0) else None
        self._turn5 = MaxTurnover5mRule(MaxTurnover5mConfig(limit_quote=cfg.max_turnover_5m_quote)) if (MaxTurnover5mRule and cfg.max_turnover_5m_quote > 0) else None
        self._cool = CooldownRule(CooldownConfig(cooldown_sec=cfg.cooldown_sec)) if (CooldownRule and cfg.cooldown_sec > 0) else None
        self._spread = SpreadCapRule(SpreadCapConfig(max_spread_pct=cfg.max_spread_pct), provider=cfg.spread_provider) if (SpreadCapRule and cfg.max_spread_pct > 0) else None
        self._dailoss = DailyLossRule(DailyLossConfig(limit_quote=cfg.daily_loss_limit_quote)) if (DailyLossRule and cfg.daily_loss_limit_quote > 0) else None
        self._corr = CorrelationManager(CorrelationConfig(groups=cfg.anti_corr_groups or [])) if (CorrelationManager and cfg.anti_corr_groups) else None

    def _budget_check(self, *, symbol: str, storage: Any) -> Tuple[bool, str, dict]:
        """
        Ğ”Ğ½ĞµĞ²Ğ½Ñ‹Ğµ Ğ±ÑĞ´Ğ¶ĞµÑ‚Ñ‹: ĞºĞ¾Ğ»-Ğ²Ğ¾ Ğ¾Ñ€Ğ´ĞµÑ€Ğ¾Ğ² Ğ¸ Ğ´Ğ½ĞµĞ²Ğ½Ğ¾Ğ¹ Ğ¾Ğ±Ğ¾Ñ€Ğ¾Ñ‚ (quote). 0 = Ğ²Ñ‹ĞºĞ»ÑÑ‡ĞµĞ½Ğ¾.
        reason: 'budget:max_orders_per_day' | 'budget:max_turnover_quote_per_day'
        """
        limit_n = int(self.cfg.max_orders_per_day or 0)
        limit_turn = Decimal(self.cfg.max_turnover_quote_per_day or 0)

        trades = getattr(storage, "trades", None)
        if (limit_n > 0) and trades:
            count = None
            if hasattr(trades, "count_orders_last_minutes"):
                try:
                    count = int(trades.count_orders_last_minutes(symbol, 1440))
                except Exception:
                    count = None
            if count is None and hasattr(trades, "list_today"):
                try:
                    count = len(trades.list_today(symbol))
                except Exception:
                    count = None
            if isinstance(count, int) and count >= limit_n > 0:
                return False, "budget:max_orders_per_day", {"count": count, "limit": limit_n}

        if (limit_turn > 0) and trades and hasattr(trades, "daily_turnover_quote"):
            try:
                turn = trades.daily_turnover_quote(symbol)
                if turn >= limit_turn:
                    return False, "budget:max_turnover_quote_per_day", {
                        "turnover": str(turn), "limit": str(limit_turn)
                    }
            except Exception:
                pass

        return True, "ok", {}

    def check(self, *, symbol: str, storage: Any) -> Tuple[bool, str, dict]:
        """
        Ğ’Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ (ok, reason, extra). ĞĞ¸ĞºĞ°ĞºĞ¸Ñ… side-effects.
        reason:
          - 'ok'
          - 'budget:*'
          - 'cooldown' | 'orders_5m' | 'turnover_5m' | 'spread' | 'daily_loss' | 'correlation'
          - 'loss_streak' | 'max_drawdown'
        """
        # Ğ±ÑĞ´Ğ¶ĞµÑ‚Ñ‹
        ok, why, extra = self._budget_check(symbol=symbol, storage=storage)
        if not ok:
            inc("budget_exceeded_total", symbol=symbol, type=why.split(":", 1)[-1])
            return False, why, extra

        trades = getattr(storage, "trades", None)
        positions = getattr(storage, "positions", None)

        # cooldown
        if self._cool and trades:
            ok, why, extra = self._cool.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # 5m ĞºĞ°Ğ¿Ñ‹
        if self._orders5 and trades:
            ok, why, extra = self._orders5.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        if self._turn5 and trades:
            ok, why, extra = self._turn5.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # Ğ°Ğ½Ñ‚Ğ¸ĞºĞ¾Ñ€Ñ€ĞµĞ»ÑÑ†Ğ¸Ñ
        if self._corr and positions:
            ok, why, extra = self._corr.check(symbol=symbol, positions_repo=positions)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # ÑĞ¿Ñ€ĞµĞ´
        if self._spread:
            ok, why, extra = self._spread.check(symbol=symbol)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # Ğ´Ğ½ĞµĞ²Ğ½Ğ¾Ğ¹ ÑƒĞ±Ñ‹Ñ‚Ğ¾Ğº
        if self._dailoss and trades:
            ok, why, extra = self._dailoss.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        if trades is None:
            return True, "ok", {"note": "no_trades_repo"}

        # loss streak
        ok, why, extra = self._loss.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            return False, why, extra

        # max drawdown
        ok, why, extra = self._dd.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            return False, why, extra

        return True, "ok", {}

    # ---- Ğ‘ÑĞºĞ¾Ğ¼Ğ¿Ğ°Ñ‚ Ğ´Ğ»Ñ ÑÑ‚Ğ°Ñ€Ñ‹Ñ… Ğ²Ñ‹Ğ·Ğ¾Ğ²Ğ¾Ğ² ----
    def can_execute(self, symbol: str, storage: Any) -> bool:
        ok, _, _ = self.check(symbol=symbol, storage=storage)
        return ok
