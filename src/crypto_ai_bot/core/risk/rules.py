# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations
from typing import Any, Dict, Optional
from crypto_ai_bot.core._time import now_ms

Result = Dict[str, Any]

def ok(**extra) -> Result:
    r = {"ok": True}
    r.update(extra)
    return r

def blocked(code: str, **extra) -> Result:
    r = {"ok": False, "code": code}
    r.update(extra)
    return r

# ---- Вспомогательные безопасные геттеры

def _cfg(cfg: Any, name: str, default: Any) -> Any:
    return getattr(cfg, name, default)

def _float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)

# ---- Правила

def check_time_sync(*, cfg: Any, external: Optional[Any] = None, **_ignored) -> Result:
    """Проверка дрейфа времени (если есть внешний источник). Иначе — ок."""
    max_drift_ms = int(_cfg(cfg, "MAX_TIME_DRIFT_MS", 15_000))
    if not external or not hasattr(external, "time_ms"):
        return ok(skip="no_external_time")
    try:
        ext = int(external.time_ms())
    except Exception:
        return ok(skip="ext_time_failed")
    drift = abs(now_ms() - ext)
    if drift > max_drift_ms:
        return blocked("time_drift", drift_ms=drift, max_ms=max_drift_ms)
    return ok(drift_ms=drift)

def check_hours(*, cfg: Any, **_ignored) -> Result:
    """Окно торговли по UTC-часам. Если не задано — всегда ок."""
    hours = getattr(cfg, "RISK_HOURS_UTC", None)
    if not hours:
        return ok(skip="no_hours")
    try:
        start, end = hours  # (int, int)
    except Exception:
        return ok(skip="bad_hours_cfg")
    import datetime as _dt, time as _t
    hour_utc = _dt.datetime.utcfromtimestamp(_t.time()).hour
    if start <= end:
        allowed = (start <= hour_utc < end)
    else:
        allowed = not (end <= hour_utc < start)
    if not allowed:
        return blocked("outside_hours", hour=hour_utc, window=hours)
    return ok(hour=hour_utc)

def check_spread(*, cfg: Any, broker: Any, symbol: str, **_ignored) -> Result:
    """Ширина спреда не выше порога."""
    max_spread_bps = _float(_cfg(cfg, "MAX_SPREAD_BPS", 50.0), 50.0)
    try:
        tkr = broker.fetch_ticker(symbol) or {}
    except Exception as e:
        return blocked("ticker_failed", error=str(e))
    bid = _float(tkr.get("bid"), 0.0)
    ask = _float(tkr.get("ask"), 0.0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return blocked("bad_quote")
    mid = (ask + bid) / 2.0
    spread_bps = ((ask - bid) / mid) * 10_000.0
    if spread_bps > max_spread_bps:
        return blocked("spread_too_wide", spread_bps=spread_bps, max_spread_bps=max_spread_bps)
    return ok(spread_bps=spread_bps)

def check_max_exposure(*, cfg: Any, positions_repo: Any, symbol: str, **_ignored) -> Result:
    """Ограничение на число одновременных лонгов и повтор на тот же символ."""
    max_positions = int(_cfg(cfg, "MAX_POSITIONS", 1))
    if hasattr(positions_repo, "count"):
        try:
            total = int(positions_repo.count() or 0)
        except Exception:
            total = 0
    else:
        total = 0
    if total >= max_positions:
        return blocked("max_positions", current=total, limit=max_positions)

    # блокировать повторный вход в тот же символ, если уже лонг
    if hasattr(positions_repo, "get"):
        row = positions_repo.get(symbol)
        if row:
            qty = _float(row.get("qty"), 0.0)
            if qty > 0:
                return blocked("symbol_already_long", qty=qty)
    return ok(total=total)

def check_drawdown(*, cfg: Any, trades_repo: Any, lookback_ms: Optional[int] = None, **_ignored) -> Result:
    """Макс. просадка по реализованному PnL за окно."""
    max_dd = _float(_cfg(cfg, "RISK_MAX_DRAWDOWN_PCT", 10.0), 10.0)
    window = int(lookback_ms or _cfg(cfg, "RISK_DRAWDOWN_LOOKBACK_MS", 7 * 86_400_000))
    since = now_ms() - window
    if not hasattr(trades_repo, "realized_pnl_since_ms"):
        return ok(skip="no_pnl_fn")
    try:
        pnl_pct = _float(trades_repo.realized_pnl_since_ms(since_ms=since).get("pnl_pct"), 0.0)
    except Exception:
        return ok(skip="pnl_calc_failed")
    if pnl_pct <= -max_dd:
        return blocked("drawdown_limit", pnl_pct=pnl_pct, max_dd=max_dd)
    return ok(pnl_pct=pnl_pct)

def check_sequence_losses(*, cfg: Any, trades_repo: Any, **_ignored) -> Result:
    """Серия подряд убыточных сделок."""
    max_losses = int(_cfg(cfg, "RISK_MAX_LOSSES", 3))
    if max_losses <= 0 or not hasattr(trades_repo, "consecutive_losses"):
        return ok(skip="no_seq_fn")
    try:
        seq = int(trades_repo.consecutive_losses() or 0)
    except Exception:
        return ok(skip="seq_calc_failed")
    if seq >= max_losses:
        return blocked("loss_streak", streak=seq, limit=max_losses)
    return ok(streak=seq)
