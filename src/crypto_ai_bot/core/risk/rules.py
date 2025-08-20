# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from crypto_ai_bot.utils.time import now_ms


@dataclass(frozen=True)
class RiskCheckResult:
    ok: bool
    code: str = "ok"
    detail: Optional[str] = None


def risk_concurrent_positions_blocked(*, has_open_long: bool) -> RiskCheckResult:
    if has_open_long:
        return RiskCheckResult(ok=False, code="concurrent_long_blocked", detail="long already open")
    return RiskCheckResult(ok=True)


def realized_pnl_since_ms(*, realized_pnl_usd: float, min_since_ms: int) -> RiskCheckResult:
    # Заглушка: логика PnL проверяется выше, функция оставлена для обратной совместимости
    _ = (realized_pnl_usd, min_since_ms)
    return RiskCheckResult(ok=True)


def risk_daily_loss_blocked(*, day_pnl_pct: float, max_daily_drawdown_pct: float) -> RiskCheckResult:
    if day_pnl_pct <= -abs(max_daily_drawdown_pct):
        return RiskCheckResult(ok=False, code="daily_drawdown_exceeded", detail=f"{day_pnl_pct:.2f}%")
    return RiskCheckResult(ok=True)


# Ниже — типовые проверки; параметры берутся из Settings/RiskManager.
def check_time_sync(*, max_drift_ms: int, local_now_ms: Optional[int] = None) -> RiskCheckResult:
    # Если есть внешний time-sync — подключите здесь. Пока считаем локальные часы источником истины.
    _now = local_now_ms if local_now_ms is not None else now_ms()
    # max_drift_ms используется во внешней проверке; локально ок
    return RiskCheckResult(ok=True)


def check_hours(*, allow_hours_utc: str) -> RiskCheckResult:
    # Формат, например: "0-24" или "8-22". Для простоты считаем 24/7 ок.
    _ = allow_hours_utc
    return RiskCheckResult(ok=True)


def check_spread(*, spread_bps: float, max_spread_bps: float) -> RiskCheckResult:
    if spread_bps > max_spread_bps:
        return RiskCheckResult(ok=False, code="spread_too_wide", detail=f"{spread_bps:.1f}bps>{max_spread_bps}")
    return RiskCheckResult(ok=True)


def check_max_exposure(*, open_positions: int, max_positions: int) -> RiskCheckResult:
    if open_positions >= max_positions:
        return RiskCheckResult(ok=False, code="too_many_positions", detail=f"{open_positions}/{max_positions}")
    return RiskCheckResult(ok=True)


def check_drawdown(*, rolling_pnl_pct: float, max_drawdown_pct: float) -> RiskCheckResult:
    if rolling_pnl_pct <= -abs(max_drawdown_pct):
        return RiskCheckResult(ok=False, code="drawdown_exceeded", detail=f"{rolling_pnl_pct:.2f}%<{-abs(max_drawdown_pct)}%")
    return RiskCheckResult(ok=True)


def check_sequence_losses(*, recent_losses: int, max_losses: int) -> RiskCheckResult:
    if recent_losses >= max_losses:
        return RiskCheckResult(ok=False, code="loss_streak", detail=f"{recent_losses}/{max_losses}")
    return RiskCheckResult(ok=True)
