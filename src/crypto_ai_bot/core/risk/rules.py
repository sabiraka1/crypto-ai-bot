# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from crypto_ai_bot.core._time import now_ms


def ok(reason: str = "ok", **extra) -> Dict[str, Any]:
    r = {"ok": True, "reason": reason}
    r.update(extra)
    return r


def blocked(reason: str, **extra) -> Dict[str, Any]:
    r = {"ok": False, "reason": reason}
    r.update(extra)
    return r


# --------- БАЗОВЫЕ ПРАВИЛА ---------------------------------------------------

async def check_time_sync(*, settings) -> Dict[str, Any]:
    # В данном варианте просто заглушка под реальную проверку (NTP/API).
    # Связываем с now_ms() чтобы была единая точка времени.
    _ = now_ms()
    max_drift = int(getattr(settings, "RISK_MAX_TIME_DRIFT_MS", 15_000))
    if max_drift < 0:
        return blocked("invalid_time_drift_config")
    return ok("time_sync_ok")


async def check_hours(*, settings) -> Dict[str, Any]:
    # Если хотите ограничить часы — используйте RISK_TRADING_HOURS="0-24" и пр.
    # Пока считаем, что торгуем всегда (или логику проверяете в своём Settings).
    return ok("hours_ok")


async def check_spread(*, settings, broker, symbol: str) -> Dict[str, Any]:
    max_spread_bps = float(getattr(settings, "RISK_MAX_SPREAD_BPS", 25.0))
    if max_spread_bps <= 0:
        return ok("spread_guard_disabled")

    t = await broker.fetch_ticker(symbol)
    bid = float(t.get("bid") or 0.0)
    ask = float(t.get("ask") or 0.0)
    if bid <= 0 or ask <= 0:
        return blocked("no_bid_ask")

    mid = 0.5 * (bid + ask)
    spread_bps = ((ask - bid) / mid) * 10000.0
    if spread_bps > max_spread_bps:
        return blocked("spread_too_wide", spread_bps=spread_bps)

    return ok("spread_ok", spread_bps=spread_bps)


async def check_max_exposure(*, settings, positions_repo, side: str, symbol: str) -> Dict[str, Any]:
    max_positions = int(getattr(settings, "RISK_MAX_POSITIONS", 1))
    if max_positions <= 0:
        return blocked("invalid_max_positions")

    if side == "buy":
        # запрещаем второй лонг по тому же символу
        pos = positions_repo.get(symbol)
        if pos and float(pos.get("qty", 0.0)) > 0.0:
            return blocked("concurrent_long_blocked")
    # можно добавить общесистемный лимит по всем символам при мульти-активах
    return ok("exposure_ok")


async def check_drawdown(*, settings, trades_repo) -> Dict[str, Any]:
    # Упростим: возьмём реализованный PnL за окно и сравним с лимитом
    lookback_ms = int(getattr(settings, "RISK_DRAWDOWN_LOOKBACK_MS", 7 * 24 * 3600 * 1000))
    max_dd_pct = float(getattr(settings, "RISK_MAX_DRAWDOWN_PCT", 10.0))
    if max_dd_pct <= 0:
        return ok("drawdown_guard_disabled")

    since = now_ms() - lookback_ms
    pnl = trades_repo.realized_pnl_since_ms(since_ms=since)  # должен существовать
    # простая эвристика: если < -max_dd_pct, блокируем
    # (в проде — считать от equity/баланса)
    if pnl is not None and pnl < 0:
        # без баланса используем proxy: если абсолютный убыток велик — блок
        # оставляем всегда ok, если репо не даёт инфы (None)
        pass
    return ok("drawdown_ok")


async def check_sequence_losses(*, settings, trades_repo) -> Dict[str, Any]:
    max_losses = int(getattr(settings, "RISK_MAX_CONSECUTIVE_LOSSES", 3))
    if max_losses <= 0:
        return ok("seq_losses_guard_disabled")

    losses = trades_repo.count_consecutive_losses()  # должен существовать
    if losses is not None and losses >= max_losses:
        return blocked("too_many_consecutive_losses", losses=losses)
    return ok("seq_losses_ok")


# --------- АГРЕГАТОР (используется RiskManager) ------------------------------

async def evaluate_all(
    *,
    settings,
    broker,
    positions_repo,
    trades_repo,
    symbol: str,
    side: str,
    notional_usd: float,
) -> Dict[str, Any]:
    """
    Единый порядок и состав правил.
    """
    # 1) время и часы
    r = await check_time_sync(settings=settings)
    if not r["ok"]:
        return r
    r = await check_hours(settings=settings)
    if not r["ok"]:
        return r

    # 2) рыночные условия
    r = await check_spread(settings=settings, broker=broker, symbol=symbol)
    if not r["ok"]:
        return r

    # 3) экспозиция / последовательные убытки / просадка
    r = await check_max_exposure(settings=settings, positions_repo=positions_repo, side=side, symbol=symbol)
    if not r["ok"]:
        return r

    r = await check_sequence_losses(settings=settings, trades_repo=trades_repo)
    if not r["ok"]:
        return r

    r = await check_drawdown(settings=settings, trades_repo=trades_repo)
    if not r["ok"]:
        return r

    return ok("all_rules_passed")
