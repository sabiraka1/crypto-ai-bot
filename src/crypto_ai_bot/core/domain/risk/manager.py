from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec


@dataclass(frozen=True)
class RiskConfig:
    """
    Конфигурация риск-лимитов. Значения 0/None означают «лимит отключён».
    """
    cooldown_sec: int = 0
    max_spread_pct: Decimal = dec("0")
    max_position_base: Decimal = dec("0")
    max_orders_per_hour: int = 0
    daily_loss_limit_quote: Decimal = dec("0")
    max_fee_pct: Decimal = dec("0.0")
    max_slippage_pct: Decimal = dec("0.0")

    # Легаси (для обратной совместимости окружения/скриптов):
    # RISK_MAX_ORDERS_5M, SAFETY_MAX_TURNOVER_QUOTE_PER_DAY читаются здесь,
    # а применяются в use-case execute_trade (центр. проверка бюджета).
    max_orders_5m: int = 0
    safety_max_turnover_quote_per_day: Decimal = dec("0")

    @classmethod
    def from_settings(cls, s: Any) -> RiskConfig:
        """
        Без чтения ENV напрямую — только из объекта Settings.
        Любые отсутствующие поля интерпретируются как «лимит отключён».
        """
        def g(name: str, default: Any) -> Any:
            return getattr(s, name, default)

        return cls(
            cooldown_sec=int(g("RISK_COOLDOWN_SEC", 0) or 0),
            max_spread_pct=dec(str(g("RISK_MAX_SPREAD_PCT", "0") or "0")),
            max_position_base=dec(str(g("RISK_MAX_POSITION_BASE", "0") or "0")),
            max_orders_per_hour=int(g("RISK_MAX_ORDERS_PER_HOUR", 0) or 0),
            daily_loss_limit_quote=dec(str(g("RISK_DAILY_LOSS_LIMIT_QUOTE", "0") or "0")),
            max_fee_pct=dec(str(g("RISK_MAX_FEE_PCT", "0.0") or "0.0")),
            max_slippage_pct=dec(str(g("RISK_MAX_SLIPPAGE_PCT", "0.0") or "0.0")),
            # легаси
            max_orders_5m=int(g("RISK_MAX_ORDERS_5M", 0) or 0),
            safety_max_turnover_quote_per_day=dec(str(g("SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", "0") or "0")),
        )


class RiskManager:
    """
    Чистый доменный компонент. Не знает про Broker/Storage, не делает I/O.
    Содержит статические/детерминированные проверки (напр., cooldown по времени,
    базовые расчёты лимитов), а динамические (ордера/оборот/спред) — централизованы
    в use-case `execute_trade`, который и так имеет все зависимости.
    """

    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    # --- Современный метод проверки ---
    def can_execute(self, *_, **__) -> bool:
        """
        Базовый фильтр «можно ли вообще рассматривать исполнение».
        Сейчас оставляем «разрешено», так как конкретные лимиты
        проверяются внутри use-case `execute_trade`.
        Если понадобится — сюда вернём лёгкую статическую проверку, например cooldown.
        """
        return True

    # --- Обратная совместимость (alias) ---
    def allow(self, *args, **kwargs) -> bool:
        """
        Сохранён для совместимости со старым кодом/скриптами:
        прежний вызов risk.allow(...) теперь корректно отработает.
        """
        return self.can_execute(*args, **kwargs)

# --- Rule orchestration ---
try:
    from crypto_ai_bot.core.domain.risk.rule.loss_streak import LossStreakRule
    from crypto_ai_bot.core.domain.risk.rule.max_drawdown import MaxDrawdownRule
except Exception:
    # Пути на случай альтернативной структуры
    from .rule.loss_streak import LossStreakRule  # type: ignore
    from .rule.max_drawdown import MaxDrawdownRule  # type: ignore

class _RepoFacade:
    def __init__(self, storage: Any) -> None:
        # поддержка разных фасадов
        self.trades = getattr(storage, "trades", None) or getattr(getattr(storage, "repos", None) or object(), "trades", None)
        self.positions = getattr(storage, "positions", None) or getattr(getattr(storage, "repos", None) or object(), "positions", None)

class RiskManager(RiskManager):  # type: ignore[misc]
    def check(self, *, symbol: str, storage: Any) -> Tuple[bool, str]:
        """Композитная проверка правил. Возвращает (ok, reason)."""
        cfg = self.config
        repo = _RepoFacade(storage)

        # 1) Loss streak (по сегодняшним сделкам)
        if cfg.max_orders_per_hour or True:  # не завязываем на опциях, разрешаем работу правила всегда
            try:
                recent = repo.trades.list_today(symbol) if repo.trades else []
            except Exception:
                recent = []
            try:
                ls = LossStreakRule(max_streak=int(getattr(storage.settings, "RISK_MAX_LOSS_STREAK", 0) or 0), lookback_trades=10)  # type: ignore[attr-defined]
            except Exception:
                ls = LossStreakRule(max_streak=0, lookback_trades=10)  # off
            if ls.max_streak and recent:
                ok, reason = ls.check(recent)
                if not ok:
                    return False, f"risk.loss_streak:{reason}"

        # 2) Max daily loss / drawdown (используем дневной PnL и позицию)
        daily_pnl = Decimal("0")
        try:
            daily_pnl = repo.trades.daily_pnl_quote(symbol) if repo.trades else Decimal("0")
        except Exception:
            daily_pnl = Decimal("0")

        try:
            md = MaxDrawdownRule(
                max_drawdown_pct=Decimal(str(getattr(storage.settings, "RISK_MAX_DRAWDOWN_PCT", "0") or "0")),  # type: ignore[attr-defined]
                max_daily_loss_quote=Decimal(str(getattr(storage.settings, "RISK_DAILY_LOSS_LIMIT_QUOTE", "0") or "0")),  # type: ignore[attr-defined]
            )
        except Exception:
            md = MaxDrawdownRule()

        cur_bal = peak_bal = Decimal("0")
        # (опционально) попытаемся извлечь из storage портфельные балансы
        try:
            port = getattr(storage, "portfolio", None)
            if port:
                cur_bal = Decimal(str(getattr(port, "current_quote", "0") or "0"))
                peak_bal = Decimal(str(getattr(port, "peak_quote", "0") or "0"))
        except Exception:
            pass

        ok, reason = md.check(current_balance=cur_bal, peak_balance=peak_bal, daily_pnl=daily_pnl)
        if not ok:
            return False, f"risk.drawdown:{reason}"

        return True, "ok"
