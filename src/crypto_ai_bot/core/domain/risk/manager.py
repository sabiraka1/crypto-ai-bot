from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakRule, LossStreakConfig
from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownRule, MaxDrawdownConfig
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

# топики
try:
    from crypto_ai_bot.core.infrastructure.events.topics import (
        RISK_BLOCKED,
    )
except Exception:
    RISK_BLOCKED = "risk.blocked"

_log = get_logger("risk.manager")


@dataclass(frozen=True)
class RiskConfig:
    loss_streak_limit: int = 0                    # >=1 включает правило
    max_drawdown_pct: float = 0.0                 # >0 включает правило
    max_orders_per_day: int = 0                   # >0 включает бюджет
    max_turnover_quote_per_day: Decimal = Decimal("0")  # >0 включает бюджет

    @classmethod
    def from_settings(cls, s: Any) -> "RiskConfig":
        # Читаем мягко: если значений нет — считаем отключёнными
        return cls(
            loss_streak_limit=int(getattr(s, "RISK_LOSS_STREAK_LIMIT", 0) or 0),
            max_drawdown_pct=float(getattr(s, "RISK_MAX_DRAWDOWN_PCT", 0.0) or 0.0),
            max_orders_per_day=int(getattr(s, "SAFETY_MAX_ORDERS_PER_DAY", 0) or 0),
            max_turnover_quote_per_day=Decimal(str(getattr(s, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", 0.0) or 0.0)),
        )


class RiskManager:
    """
    Единая точка входа: check(symbol, storage) -> (ok, reason)
    Ничего не меняет в бизнес-логике — только блокирует шаг, если правила нарушены.
    """

    def __init__(self, cfg: RiskConfig, *, bus: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.bus = bus
        self._loss = LossStreakRule(LossStreakConfig(limit=cfg.loss_streak_limit))
        self._dd = MaxDrawdownRule(MaxDrawdownConfig(max_drawdown_pct=cfg.max_drawdown_pct))

    async def _publish(self, topic: str, payload: dict) -> None:
        bus = self.bus
        if bus and hasattr(bus, "publish"):
            try:
                await bus.publish(topic, payload)
            except Exception:
                _log.debug("risk_publish_failed", extra={"topic": topic}, exc_info=True)

    def _budget_check(self, *, symbol: str, storage: Any) -> tuple[bool, str, dict]:
        """
        Дневные бюджеты: кол-во ордеров и дневной оборот в quote.
        Используем имеющиеся методы репозиториев. 0 = отключено.
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
                return False, "max_orders_per_day", {"count": count, "limit": limit_n}

        if (limit_turn > 0) and trades and hasattr(trades, "daily_turnover_quote"):
            try:
                turn = trades.daily_turnover_quote(symbol)
                if turn >= limit_turn:
                    return False, "max_turnover_quote_per_day", {"turnover": str(turn), "limit": str(limit_turn)}
            except Exception:
                pass

        return True, "ok", {}

    def check(self, *, symbol: str, storage: Any) -> tuple[bool, str]:
        """
        Синхронный API — вызывается из оркестратора до шага исполнения.
        Возвращает (ok, reason). Публикатор событий вызывается асинхронно снаружи при необходимости.
        """
        # ---- бюджеты (мягкая проверка) ----
        ok, why, extra = self._budget_check(symbol=symbol, storage=storage)
        if not ok:
            # события/метрики
            inc("budget_exceeded_total", symbol=symbol, type=why)
            # оставляем строковый топик для совместимости с существующими подписчиками
            # (в твоём Telegram-подписчике уже есть обработчик 'budget.exceeded')
            # publish можно сделать снаружи, но оставим тут мягкий вариант через async helper
            try:
                import asyncio
                asyncio.create_task(self._publish("budget.exceeded", {"symbol": symbol, "type": why, **extra}))
            except Exception:
                pass
            return False, f"budget:{why}"

        trades = getattr(storage, "trades", None)
        if trades is None:
            return True, "no_trades_repo"

        # ---- loss streak ----
        ok, why, extra = self._loss.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            try:
                import asyncio
                asyncio.create_task(self._publish(RISK_BLOCKED, {"symbol": symbol, "reason": why, **extra}))
            except Exception:
                pass
            return False, why

        # ---- max drawdown ----
        ok, why, extra = self._dd.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            try:
                import asyncio
                asyncio.create_task(self._publish(RISK_BLOCKED, {"symbol": symbol, "reason": why, **extra}))
            except Exception:
                pass
            return False, why

        return True, "ok"
