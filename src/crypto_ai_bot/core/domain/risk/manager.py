from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

# Domain rules
from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakConfig, LossStreakRule
from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownConfig, MaxDrawdownRule

# Optional rules â€” Ğ¼Ğ¾Ğ³ÑƒÑ‚ Ğ¾Ñ‚ÑÑƒÑ‚ÑÑ‚Ğ²Ğ¾Ğ²Ğ°Ñ‚ÑŒ Ğ² ÑĞ±Ğ¾Ñ€ĞºĞµ
try:
    from crypto_ai_bot.core.domain.risk.rules.max_orders_5m import MaxOrders5mConfig, MaxOrders5mRule
except ImportError:  # pragma: no cover
    MaxOrders5mRule = None  # type: ignore[assignment]
    MaxOrders5mConfig = None  # type: ignore[assignment]

try:
    from crypto_ai_bot.core.domain.risk.rules.max_turnover_5m import MaxTurnover5mConfig, MaxTurnover5mRule
except ImportError:  # pragma: no cover
    MaxTurnover5mRule = None  # type: ignore[assignment]
    MaxTurnover5mConfig = None  # type: ignore[assignment]

try:
    from crypto_ai_bot.core.domain.risk.rules.cooldown import CooldownConfig, CooldownRule
except ImportError:  # pragma: no cover
    CooldownRule = None  # type: ignore[assignment]
    CooldownConfig = None  # type: ignore[assignment]

try:
    from crypto_ai_bot.core.domain.risk.rules.spread_cap import SpreadCapConfig, SpreadCapRule
except ImportError:  # pragma: no cover
    SpreadCapRule = None  # type: ignore[assignment]
    SpreadCapConfig = None  # type: ignore[assignment]

try:
    from crypto_ai_bot.core.domain.risk.rules.daily_loss import DailyLossConfig, DailyLossRule
except ImportError:  # pragma: no cover
    DailyLossRule = None  # type: ignore[assignment]
    DailyLossConfig = None  # type: ignore[assignment]

try:
    from crypto_ai_bot.core.domain.risk.rules.correlation import CorrelationConfig, CorrelationManager
except ImportError:  # pragma: no cover
    CorrelationManager = None  # type: ignore[assignment]
    CorrelationConfig = None  # type: ignore[assignment]

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("risk.manager")


@dataclass(frozen=True)
class RiskConfig:
    """Risk management configuration."""

    # Hard limits
    loss_streak_limit: int = 0
    max_drawdown_pct: float = 0.0
    max_orders_per_day: int = 0
    max_turnover_quote_per_day: Decimal = Decimal("0")

    # Soft limits (0 = disabled)
    max_orders_5m: int = 0
    max_turnover_5m_quote: Decimal = Decimal("0")
    cooldown_sec: int = 0
    max_spread_pct: float = 0.0
    daily_loss_limit_quote: Decimal = Decimal("0")

    # Anti-correlation
    anti_corr_groups: list[list[str]] | None = None

    # Spread provider: Ñ„ÑƒĞ½ĞºÑ†Ğ¸Ñ, Ğ²Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ÑÑ‰Ğ°Ñ Ñ‚ĞµĞºÑƒÑ‰Ğ¸Ğ¹ ÑĞ¿Ñ€ĞµĞ´ Ğ² %
    # Ğ¡Ğ¸Ğ³Ğ½Ğ°Ñ‚ÑƒÑ€Ğ° Ğ¼Ğ¾Ğ¶ĞµÑ‚ Ğ¾Ñ‚Ğ»Ğ¸Ñ‡Ğ°Ñ‚ÑŒÑÑ Ğ² Ñ‚Ğ²Ğ¾Ñ‘Ğ¼ Ğ¿Ñ€Ğ¾ĞµĞºÑ‚Ğµ â€” Ğ¼Ğ¸Ğ½Ğ¸Ğ¼Ğ°Ğ»ÑŒĞ½Ğ¾ Ğ¿Ñ€ĞµĞ´Ğ¿Ğ¾Ğ»Ğ°Ğ³Ğ°ĞµĞ¼ symbol -> float (%)
    spread_provider: Callable[[str], float] | None = None

    @classmethod
    def from_settings(cls, s: object, *, spread_provider: Callable[[str], float] | None = None) -> RiskConfig:
        """Create config from settings object."""
        groups = getattr(s, "RISK_ANTI_CORR_GROUPS", None) or None
        if isinstance(groups, str):
            try:
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
    Pure API for application layer:
    check(symbol, storage) -> (ok: bool, reason: str, extra: dict)
    No event bus or side effects inside domain.
    """

    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self._loss = LossStreakRule(LossStreakConfig(limit=cfg.loss_streak_limit))
        self._dd = MaxDrawdownRule(MaxDrawdownConfig(max_drawdown_pct=cfg.max_drawdown_pct))

        self._orders5 = (
            MaxOrders5mRule(MaxOrders5mConfig(limit=cfg.max_orders_5m))
            if (MaxOrders5mRule and cfg.max_orders_5m > 0)
            else None
        )
        self._turn5 = (
            MaxTurnover5mRule(MaxTurnover5mConfig(limit_quote=cfg.max_turnover_5m_quote))
            if (MaxTurnover5mRule and cfg.max_turnover_5m_quote > 0)
            else None
        )
        self._cool = (
            CooldownRule(CooldownConfig(cooldown_sec=cfg.cooldown_sec))
            if (CooldownRule and cfg.cooldown_sec > 0)
            else None
        )
        self._spread = (
            SpreadCapRule(SpreadCapConfig(max_spread_pct=cfg.max_spread_pct), provider=cfg.spread_provider)
            if (SpreadCapRule and cfg.max_spread_pct > 0)
            else None
        )
        self._dailoss = (
            DailyLossRule(DailyLossConfig(limit_quote=cfg.daily_loss_limit_quote))
            if (DailyLossRule and cfg.daily_loss_limit_quote > 0)
            else None
        )
        self._corr = (
            CorrelationManager(CorrelationConfig(groups=cfg.anti_corr_groups or []))
            if (CorrelationManager and cfg.anti_corr_groups)
            else None
        )

    def _budget_check(self, *, symbol: str, storage: object) -> tuple[bool, str, dict]:
        """
        Daily budgets: order count and turnover in quote currency. 0 = disabled.
        storage â€” Ğ¿Ñ€Ğ¾Ğ¸Ğ·Ğ²Ğ¾Ğ»ÑŒĞ½Ğ°Ñ Ñ€ĞµĞ°Ğ»Ğ¸Ğ·Ğ°Ñ†Ğ¸Ñ Ñ .trades Ğ¸ Ğ¼ĞµÑ‚Ğ¾Ğ´Ğ°Ğ¼Ğ¸, ĞµÑĞ»Ğ¸ Ğ´Ğ¾ÑÑ‚ÑƒĞ¿Ğ½Ñ‹.
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
            if isinstance(count, int) and count >= limit_n:
                return False, "budget:max_orders_per_day", {"count": count, "limit": limit_n}

        if (limit_turn > 0) and trades and hasattr(trades, "daily_turnover_quote"):
            try:
                turn = trades.daily_turnover_quote(symbol)
                if turn >= limit_turn:
                    return (
                        False,
                        "budget:max_turnover_quote_per_day",
                        {"turnover": str(turn), "limit": str(limit_turn)},
                    )
            except Exception:
                pass

        return True, "ok", {}

    def check(self, *, symbol: str, storage: object) -> tuple[bool, str, dict]:
        """Return (ok, reason, extra)."""
        ok, why, extra = self._budget_check(symbol=symbol, storage=storage)
        if not ok:
            inc("budget_exceeded_total", symbol=symbol, type=why.split(":", 1)[-1])
            return False, why, extra

        trades = getattr(storage, "trades", None)
        positions = getattr(storage, "positions", None)

        # Optional checks (ĞµÑĞ»Ğ¸ Ğ¼Ğ¾Ğ´ÑƒĞ»ÑŒ/Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ¾ Ğ½Ğµ Ğ¿Ğ¾Ğ´ĞºĞ»ÑÑ‡ĞµĞ½Ğ¾ â€” Ğ¿Ñ€Ğ¾Ğ¿ÑƒÑĞºĞ°ĞµĞ¼)
        for rule in [self._cool, self._orders5, self._turn5, self._corr, self._spread, self._dailoss]:
            if rule is not None:
                try:
                    ok, why, extra = rule.check(symbol=symbol, trades_repo=trades, positions_repo=positions)
                    if not ok:
                        inc("risk_block_total", symbol=symbol, reason=why)
                        return False, why, extra
                except TypeError:
                    # ĞĞµĞºĞ¾Ñ‚Ğ¾Ñ€Ñ‹Ğµ Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ° Ğ½Ğµ Ñ‚Ñ€ĞµĞ±ÑƒÑÑ‚ Ğ¾Ğ±Ğ° Ñ€ĞµĞ¿Ğ¾Ğ·Ğ¸Ñ‚Ğ¾Ñ€Ğ¸Ñ
                    try:
                        ok, why, extra = rule.check(symbol=symbol, trades_repo=trades)
                        if not ok:
                            inc("risk_block_total", symbol=symbol, reason=why)
                            return False, why, extra
                    except Exception:
                        continue
                except Exception:
                    continue

        if trades is None:
            return True, "ok", {"note": "no_trades_repo"}

        ok, why, extra = self._loss.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            return False, why, extra

        ok, why, extra = self._dd.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            return False, why, extra

        return True, "ok", {}

    def can_execute(self, symbol: str, storage: object) -> bool:
        ok, _, _ = self.check(symbol=symbol, storage=storage)
        return ok
