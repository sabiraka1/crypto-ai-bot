from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Domain rules (чистый слой)
from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakConfig, LossStreakRule
from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownConfig, MaxDrawdownRule

# Опциональные правила (мягкое подключение)
try:
    from crypto_ai_bot.core.domain.risk.rules.max_orders_5m import MaxOrders5mConfig, MaxOrders5mRule
except ImportError:
    MaxOrders5mRule = None  # type: ignore
    MaxOrders5mConfig = None  # type: ignore

try:
    from crypto_ai_bot.core.domain.risk.rules.max_turnover_5m import MaxTurnover5mConfig, MaxTurnover5mRule
except ImportError:
    MaxTurnover5mRule = None  # type: ignore
    MaxTurnover5mConfig = None  # type: ignore

try:
    from crypto_ai_bot.core.domain.risk.rules.cooldown import CooldownConfig, CooldownRule
except ImportError:
    CooldownRule = None  # type: ignore
    CooldownConfig = None  # type: ignore

try:
    from crypto_ai_bot.core.domain.risk.rules.spread_cap import SpreadCapConfig, SpreadCapRule
except ImportError:
    SpreadCapRule = None  # type: ignore
    SpreadCapConfig = None  # type: ignore

try:
    from crypto_ai_bot.core.domain.risk.rules.daily_loss import DailyLossConfig, DailyLossRule
except ImportError:
    DailyLossRule = None  # type: ignore
    DailyLossConfig = None  # type: ignore

try:
    from crypto_ai_bot.core.domain.risk.rules.correlation_manager import CorrelationConfig, CorrelationManager
except ImportError:
    CorrelationManager = None  # type: ignore
    CorrelationConfig = None  # type: ignore

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("risk.manager")


@dataclass(frozen=True)
class RiskConfig:
    """Risk management configuration."""

    # Базовые правила
    loss_streak_limit: int = 0
    max_drawdown_pct: float = 0.0
    max_orders_per_day: int = 0
    max_turnover_quote_per_day: Decimal = Decimal("0")

    # Мягкие лимиты (0 = выключено)
    max_orders_5m: int = 0
    max_turnover_5m_quote: Decimal = Decimal("0")
    cooldown_sec: int = 0
    max_spread_pct: float = 0.0
    daily_loss_limit_quote: Decimal = Decimal("0")

    # Антикорреляция
    anti_corr_groups: list[list[str]] | None = None

    # Провайдер спреда (если None — SpreadCapRule пропускается)
    spread_provider: callable | None = None

    @classmethod
    def from_settings(cls, s: Any, *, spread_provider: callable | None = None) -> RiskConfig:
        """Create config from settings object."""
        groups = getattr(s, "RISK_ANTI_CORR_GROUPS", None) or None
        if isinstance(groups, str):
            try:
                # Format: "BTC/USDT|ETH/USDT;XRP/USDT|ADA/USDT"
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
    Чистый API для application слоя:
    check(symbol, storage) -> (ok: bool, reason: str, extra: dict)
    Никаких публикаций/шины внутри domain.
    """

    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

        # Базовые правила
        self._loss = LossStreakRule(LossStreakConfig(limit=cfg.loss_streak_limit))
        self._dd = MaxDrawdownRule(MaxDrawdownConfig(max_drawdown_pct=cfg.max_drawdown_pct))

        # Опциональные правила
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

    def _budget_check(self, *, symbol: str, storage: Any) -> tuple[bool, str, dict]:
        """
        Дневные бюджеты: кол-во ордеров и дневной оборот (quote). 0 = выключено.
        reason: 'budget:max_orders_per_day' | 'budget:max_turnover_quote_per_day'
        """
        limit_n = int(self.cfg.max_orders_per_day or 0)
        limit_turn = Decimal(self.cfg.max_turnover_quote_per_day or 0)

        trades = getattr(storage, "trades", None)

        # Check daily orders limit
        if (limit_n > 0) and trades:
            count = None
            if hasattr(trades, "count_orders_last_minutes"):
                try:
                    count = int(trades.count_orders_last_minutes(symbol, 1440))  # 24 hours
                except Exception:
                    count = None

            if count is None and hasattr(trades, "list_today"):
                try:
                    count = len(trades.list_today(symbol))
                except Exception:
                    count = None

            if isinstance(count, int) and count >= limit_n:
                return False, "budget:max_orders_per_day", {"count": count, "limit": limit_n}

        # Check daily turnover limit
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

    def check(self, *, symbol: str, storage: Any) -> tuple[bool, str, dict]:
        """
        Возвращает (ok, reason, extra). Никаких side-effects.
        reason:
          - 'ok'
          - 'budget:*'
          - 'cooldown' | 'orders_5m' | 'turnover_5m' | 'spread' | 'daily_loss' | 'correlation'
          - 'loss_streak' | 'max_drawdown'
        """
        # Бюджеты
        ok, why, extra = self._budget_check(symbol=symbol, storage=storage)
        if not ok:
            inc("budget_exceeded_total", symbol=symbol, type=why.split(":", 1)[-1])
            return False, why, extra

        trades = getattr(storage, "trades", None)
        positions = getattr(storage, "positions", None)

        # Cooldown check
        if self._cool and trades:
            ok, why, extra = self._cool.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # 5-minute caps
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

        # Anti-correlation check
        if self._corr and positions:
            ok, why, extra = self._corr.check(symbol=symbol, positions_repo=positions)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # Spread check
        if self._spread:
            ok, why, extra = self._spread.check(symbol=symbol)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # Daily loss check
        if self._dailoss and trades:
            ok, why, extra = self._dailoss.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # Если нет репозитория trades — пропускаем streak/drawdown
        if trades is None:
            return True, "ok", {"note": "no_trades_repo"}

        # Loss streak
        ok, why, extra = self._loss.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            return False, why, extra

        # Max drawdown
        ok, why, extra = self._dd.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            return False, why, extra

        return True, "ok", {}

    # ---- Совместимость для старых вызовов ----
    def can_execute(self, symbol: str, storage: Any) -> bool:
        ok, _, _ = self.check(symbol=symbol, storage=storage)
        return ok
