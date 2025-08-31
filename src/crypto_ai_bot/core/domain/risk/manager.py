from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

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
    def from_settings(cls, s: Any) -> "RiskConfig":
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
