from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakRule, LossStreakConfig
from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownRule, MaxDrawdownConfig

# Новые правила (мягко подключаем; если файлов нет — импорт не упадёт)
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

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

# ЕДИНЫЕ ТЕМЫ СОБЫТИЙ (без магических строк)
from crypto_ai_bot.core.application import events_topics as EVT

_log = get_logger("risk.manager")


@dataclass(frozen=True)
class RiskConfig:
    # базовые (были)
    loss_streak_limit: int = 0
    max_drawdown_pct: float = 0.0
    max_orders_per_day: int = 0
    max_turnover_quote_per_day: Decimal = Decimal("0")

    # новые мягкие лимиты (0/0.0 = выключено)
    max_orders_5m: int = 0
    max_turnover_5m_quote: Decimal = Decimal("0")
    cooldown_sec: int = 0
    max_spread_pct: float = 0.0
    daily_loss_limit_quote: Decimal = Decimal("0")

    # антикорреляция (группы символов — блокируем одновременные позиции внутри группы)
    # пример: [["BTC/USDT", "ETH/USDT"]]
    anti_corr_groups: list[list[str]] | None = None

    # опциональный провайдер спрэда: callable -> float в процентах
    # если None — SpreadCapRule просто пропускается (не блокирует)
    spread_provider: Optional[callable] = None

    @classmethod
    def from_settings(cls, s: Any, *, spread_provider: Optional[callable] = None) -> "RiskConfig":
        """
        Читаем мягко: если значений нет — считаем отключёнными.
        spread_provider можно передать снаружи (например, обёртка над broker.fetch_ticker).
        """
        groups = getattr(s, "RISK_ANTI_CORR_GROUPS", None) or None
        # допускаем задание групп и как список строк через запятую
        if isinstance(groups, str):
            try:
                # "BTC/USDT|ETH/USDT;XRP/USDT|ADA/USDT"
                raw_groups = [g for g in groups.split(";") if g]
                groups = [g.split("|") for g in raw_groups]
            except Exception:
                groups = None

        return cls(
            loss_streak_limit=int(getattr(s, "RISK_LOSS_STREAK_LIMIT", 0) or 0),
            max_drawdown_pct=float(getattr(s, "RISK_MAX_DRAWDOWN_PCT", 0.0) or 0.0),
            max_orders_per_day=int(getattr(s, "SAFETY_MAX_ORDERS_PER_DAY", 0) or 0),
            max_turnover_quote_per_day=Decimal(str(getattr(s, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", 0.0) or 0.0)),
            max_orders_5m=int(getattr(s, "RISK_MAX_ORDERS_5M", 0) or 0),
            max_turnover_5m_quote=Decimal(str(getattr(s, "RISK_MAX_TURNOVER_5M_QUOTE", 0.0) or 0.0)),
            cooldown_sec=int(getattr(s, "RISK_COOLDOWN_SEC", 0) or 0),
            max_spread_pct=float(getattr(s, "RISK_MAX_SPREAD_PCT", 0.0) or 0.0),
            daily_loss_limit_quote=Decimal(str(getattr(s, "RISK_DAILY_LOSS_LIMIT_QUOTE", 0.0) or 0.0)),
            anti_corr_groups=groups,
            spread_provider=spread_provider,
        )


class RiskManager:
    """
    Единая точка входа: check(symbol, storage) -> (ok, reason)
    Ничего не меняет в бизнес-логике — только блокирует шаг, если правила нарушены.
    """

    def __init__(self, cfg: RiskConfig, *, bus: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.bus = bus

        # базовые
        self._loss = LossStreakRule(LossStreakConfig(limit=cfg.loss_streak_limit))
        self._dd = MaxDrawdownRule(MaxDrawdownConfig(max_drawdown_pct=cfg.max_drawdown_pct))

        # новые (мягкое подключение)
        self._orders5 = MaxOrders5mRule(MaxOrders5mConfig(limit=cfg.max_orders_5m)) if (MaxOrders5mRule and cfg.max_orders_5m > 0) else None
        self._turn5 = MaxTurnover5mRule(MaxTurnover5mConfig(limit_quote=cfg.max_turnover_5m_quote)) if (MaxTurnover5mRule and cfg.max_turnover_5m_quote > 0) else None
        self._cool = CooldownRule(CooldownConfig(cooldown_sec=cfg.cooldown_sec)) if (CooldownRule and cfg.cooldown_sec > 0) else None
        self._spread = SpreadCapRule(SpreadCapConfig(max_spread_pct=cfg.max_spread_pct), provider=cfg.spread_provider) if (SpreadCapRule and cfg.max_spread_pct > 0) else None
        self._dailoss = DailyLossRule(DailyLossConfig(limit_quote=cfg.daily_loss_limit_quote)) if (DailyLossRule and cfg.daily_loss_limit_quote > 0) else None
        self._corr = CorrelationManager(CorrelationConfig(groups=cfg.anti_corr_groups or [])) if (CorrelationManager and cfg.anti_corr_groups) else None

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
        # ---- дневные бюджеты ----
        ok, why, extra = self._budget_check(symbol=symbol, storage=storage)
        if not ok:
            inc("budget_exceeded_total", symbol=symbol, type=why)
            try:
                import asyncio
                asyncio.create_task(self._publish(EVT.BUDGET_EXCEEDED, {"symbol": symbol, "type": why, **extra}))
            except Exception:
                pass
            return False, f"budget:{why}"

        trades = getattr(storage, "trades", None)
        positions = getattr(storage, "positions", None)

        # ---- cooldown (минимальный интервал между сделками) ----
        if self._cool and trades:
            ok, why, extra = self._cool.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why

        # ---- burst-защита (5m капы) ----
        if self._orders5 and trades:
            ok, why, extra = self._orders5.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why

        if self._turn5 and trades:
            ok, why, extra = self._turn5.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why

        # ---- антикорреляция (например, BTC/USDT vs ETH/USDT) ----
        if self._corr and positions:
            ok, why, extra = self._corr.check(symbol=symbol, positions_repo=positions)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why

        # ---- ограничение по спрэду (если есть провайдер спрэда) ----
        if self._spread:
            ok, why, extra = self._spread.check(symbol=symbol)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why

        # ---- дневной лимит убытка по реализованному PnL ----
        if self._dailoss and trades:
            ok, why, extra = self._dailoss.check(symbol=symbol, trades_repo=trades)
            if not ok:
                inc("risk_block_total", symbol=symbol, reason=why)
                return False, why

        if trades is None:
            return True, "no_trades_repo"

        # ---- loss streak ----
        ok, why, extra = self._loss.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            try:
                import asyncio
                asyncio.create_task(self._publish(EVT.RISK_BLOCKED, {"symbol": symbol, "reason": why, **extra}))
            except Exception:
                pass
            return False, why

        # ---- max drawdown ----
        ok, why, extra = self._dd.check(symbol=symbol, trades_repo=trades)
        if not ok:
            inc("risk_block_total", symbol=symbol, reason=why)
            try:
                import asyncio
                asyncio.create_task(self._publish(EVT.RISK_BLOCKED, {"symbol": symbol, "reason": why, **extra}))
            except Exception:
                pass
            return False, why

        return True, "ok"
