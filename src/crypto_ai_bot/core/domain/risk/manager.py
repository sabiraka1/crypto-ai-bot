from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Tuple

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
    max_orders_5m: int = 0
    safety_max_turnover_quote_per_day: Decimal = dec("0")
    max_turnover_day: Decimal = dec("0")

    @classmethod
    def from_settings(cls, s: Any) -> RiskConfig:
        """
        Без чтения ENV напрямую — только из объекта Settings.
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
            max_turnover_day=dec(str(g("RISK_MAX_TURNOVER_DAY", "0") or "0")),
        )


class RiskManager:
    """
    Чистый доменный компонент. Не знает про Broker/Storage, не делает I/O.
    Содержит статические/детерминированные проверки.
    """

    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    def can_execute(self, *_: Any, **__: Any) -> bool:
        """
        Базовый фильтр «можно ли вообще рассматривать исполнение».
        """
        return True

    def allow(self, symbol: str, now_ms: int, storage: Any | None = None) -> Tuple[bool, str]:
        """
        Обратная совместимость - возвращает tuple (bool, str).
        Для тестов которые ожидают именно этот формат.
        """
        can = self.can_execute(symbol=symbol, now_ms=now_ms, storage=storage)
        if not can:
            return False, "risk_check_failed"
        
        if storage:
            return self.check(symbol=symbol, storage=storage)
        
        return True, "ok"

    def check(self, *, symbol: str, storage: Any) -> Tuple[bool, str]:
        """
        Композитная проверка правил. Возвращает (ok, reason).
        Расширенная версия для более сложных проверок.
        """
        # Попытаемся импортировать правила если они существуют
        try:
            from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakRule
            from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownRule
            
            # Фасад для доступа к репозиториям
            class _RepoFacade:
                def __init__(self, storage: Any) -> None:
                    self.trades = getattr(storage, "trades", None) or getattr(getattr(storage, "repos", None) or object(), "trades", None)
                    self.positions = getattr(storage, "positions", None) or getattr(getattr(storage, "repos", None) or object(), "positions", None)
            
            cfg = self.config
            repo = _RepoFacade(storage)

            # 1) Loss streak (по сегодняшним сделкам)
            if cfg.max_orders_per_hour or True:  # не завязываем на опциях, разрешаем работу правила всегда
                try:
                    recent = repo.trades.list_today(symbol) if repo.trades else []
                except Exception:
                    recent = []
                try:
                    max_streak_val = int(getattr(storage.settings, "RISK_MAX_LOSS_STREAK", 0) or 0)
                    ls = LossStreakRule(max_streak=max_streak_val, lookback_trades=10)
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
                max_dd_pct = Decimal(str(getattr(storage.settings, "RISK_MAX_DRAWDOWN_PCT", "0") or "0"))
                max_daily_loss = Decimal(str(getattr(storage.settings, "RISK_DAILY_LOSS_LIMIT_QUOTE", "0") or "0"))
                md = MaxDrawdownRule(
                    max_drawdown_pct=max_dd_pct,
                    max_daily_loss_quote=max_daily_loss,
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
            
        except ImportError:
            # Если модули с правилами не существуют, используем базовую проверку
            return True, "basic_check"