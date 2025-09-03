from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Domain-ДћВїГ‘в‚¬ДћВ°ДћВІДћВёДћВ»ДћВ° (Г‘вЂЎДћВёГ‘ВЃГ‘вЂљГ‘вЂ№ДћВ№ Г‘ВЃДћВ»ДћВѕДћВ№)
from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakConfig, LossStreakRule
from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownConfig, MaxDrawdownRule

# ДћвЂќДћВѕДћВї. ДћВїГ‘в‚¬ДћВ°ДћВІДћВёДћВ»ДћВ° (ДћВјГ‘ВЏДћВіДћВєДћВѕДћВµ ДћВїДћВѕДћВґДћВєДћВ»Г‘ВЋГ‘вЂЎДћВµДћВЅДћВёДћВµ)
try:
    from crypto_ai_bot.core.domain.risk.rules.max_orders_5m import MaxOrders5mConfig, MaxOrders5mRule
except Exception:
    MaxOrders5mRule = None  # type: ignore
    MaxOrders5mConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.max_turnover_5m import MaxTurnover5mConfig, MaxTurnover5mRule
except Exception:
    MaxTurnover5mRule = None  # type: ignore
    MaxTurnover5mConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.cooldown import CooldownConfig, CooldownRule
except Exception:
    CooldownRule = None  # type: ignore
    CooldownConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.spread_cap import SpreadCapConfig, SpreadCapRule
except Exception:
    SpreadCapRule = None  # type: ignore
    SpreadCapConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.rules.daily_loss import DailyLossConfig, DailyLossRule
except Exception:
    DailyLossRule = None  # type: ignore
    DailyLossConfig = None  # type: ignore
try:
    from crypto_ai_bot.core.domain.risk.correlation_manager import CorrelationConfig, CorrelationManager
except Exception:
    CorrelationManager = None  # type: ignore
    CorrelationConfig = None  # type: ignore

# utils ДћВІ domain ДћВґДћВѕДћВїГ‘Ж’Г‘ВЃГ‘вЂљДћВёДћВјГ‘вЂ№
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("risk.manager")


@dataclass(frozen=True)
class RiskConfig:
    # ДћВ±ДћВ°ДћВ·ДћВѕДћВІГ‘вЂ№ДћВµ
    loss_streak_limit: int = 0
    max_drawdown_pct: float = 0.0
    max_orders_per_day: int = 0
    max_turnover_quote_per_day: Decimal = Decimal("0")

    # ДћВјГ‘ВЏДћВіДћВєДћВёДћВµ ДћВ»ДћВёДћВјДћВёГ‘вЂљГ‘вЂ№ (0 = ДћВІГ‘вЂ№ДћВєДћВ»Г‘ВЋГ‘вЂЎДћВµДћВЅДћВѕ)
    max_orders_5m: int = 0
    max_turnover_5m_quote: Decimal = Decimal("0")
    cooldown_sec: int = 0
    max_spread_pct: float = 0.0
    daily_loss_limit_quote: Decimal = Decimal("0")

    # ДћВ°ДћВЅГ‘вЂљДћВёДћВєДћВѕГ‘в‚¬Г‘в‚¬ДћВµДћВ»Г‘ВЏГ‘вЂ ДћВёГ‘ВЏ
    anti_corr_groups: list[list[str]] | None = None

    # ДћВїГ‘в‚¬ДћВѕДћВІДћВ°ДћВ№ДћВґДћВµГ‘в‚¬ Г‘ВЃДћВїГ‘в‚¬Г‘ВЌДћВґДћВ° (ДћВµГ‘ВЃДћВ»ДћВё None Гўв‚¬вЂќ SpreadCapRule ДћВїГ‘в‚¬ДћВѕДћВїГ‘Ж’Г‘ВЃДћВєДћВ°ДћВµГ‘вЂљГ‘ВЃГ‘ВЏ)
    spread_provider: callable | None = None

    @classmethod
    def from_settings(cls, s: Any, *, spread_provider: callable | None = None) -> RiskConfig:
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
    ДћВ§ДћВёГ‘ВЃГ‘вЂљГ‘вЂ№ДћВ№ API ДћВґДћВ»Г‘ВЏ application Г‘ВЃДћВ»ДћВѕГ‘ВЏ:
    check(symbol, storage) -> (ok: bool, reason: str, extra: dict)
    ДћВќДћВёДћВєДћВ°ДћВєДћВёГ‘вЂ¦ ДћВїГ‘Ж’ДћВ±ДћВ»ДћВёДћВєДћВ°Г‘вЂ ДћВёДћВ№/Г‘Л†ДћВёДћВЅГ‘вЂ№ ДћВІДћВЅГ‘Ж’Г‘вЂљГ‘в‚¬ДћВё domain.
    """

    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

        # ДћВ±ДћВ°ДћВ·ДћВѕДћВІГ‘вЂ№ДћВµ
        self._loss = LossStreakRule(LossStreakConfig(limit=cfg.loss_streak_limit))
        self._dd = MaxDrawdownRule(MaxDrawdownConfig(max_drawdown_pct=cfg.max_drawdown_pct))

        # ДћВґДћВѕДћВї. ДћВїГ‘в‚¬ДћВ°ДћВІДћВёДћВ»ДћВ°
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
        ДћвЂќДћВЅДћВµДћВІДћВЅГ‘вЂ№ДћВµ ДћВ±Г‘ВЋДћВґДћВ¶ДћВµГ‘вЂљГ‘вЂ№: ДћВєДћВѕДћВ»-ДћВІДћВѕ ДћВѕГ‘в‚¬ДћВґДћВµГ‘в‚¬ДћВѕДћВІ ДћВё ДћВґДћВЅДћВµДћВІДћВЅДћВѕДћВ№ ДћВѕДћВ±ДћВѕГ‘в‚¬ДћВѕГ‘вЂљ (quote). 0 = ДћВІГ‘вЂ№ДћВєДћВ»Г‘ВЋГ‘вЂЎДћВµДћВЅДћВѕ.
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
        ДћвЂ™ДћВѕДћВ·ДћВІГ‘в‚¬ДћВ°Г‘вЂ°ДћВ°ДћВµГ‘вЂљ (ok, reason, extra). ДћВќДћВёДћВєДћВ°ДћВєДћВёГ‘вЂ¦ side-effects.
        reason:
          - 'ok'
          - 'budget:*'
          - 'cooldown' | 'orders_5m' | 'turnover_5m' | 'spread' | 'daily_loss' | 'correlation'
          - 'loss_streak' | 'max_drawdown'
        """
        # ДћВ±Г‘ВЋДћВґДћВ¶ДћВµГ‘вЂљГ‘вЂ№
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

        # 5m ДћВєДћВ°ДћВїГ‘вЂ№
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

        # ДћВ°ДћВЅГ‘вЂљДћВёДћВєДћВѕГ‘в‚¬Г‘в‚¬ДћВµДћВ»Г‘ВЏГ‘вЂ ДћВёГ‘ВЏ
        if self._corr and positions:
            ok, why, extra = self._corr.check(symbol=symbol, positions_repo=positions)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # Г‘ВЃДћВїГ‘в‚¬ДћВµДћВґ
        if self._spread:
            ok, why, extra = self._spread.check(symbol=symbol)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why, extra

        # ДћВґДћВЅДћВµДћВІДћВЅДћВѕДћВ№ Г‘Ж’ДћВ±Г‘вЂ№Г‘вЂљДћВѕДћВє
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

    # ---- ДћвЂГ‘ВЌДћВєДћВѕДћВјДћВїДћВ°Г‘вЂљ ДћВґДћВ»Г‘ВЏ Г‘ВЃГ‘вЂљДћВ°Г‘в‚¬Г‘вЂ№Г‘вЂ¦ ДћВІГ‘вЂ№ДћВ·ДћВѕДћВІДћВѕДћВІ ----
    def can_execute(self, symbol: str, storage: Any) -> bool:
        ok, _, _ = self.check(symbol=symbol, storage=storage)
        return ok
