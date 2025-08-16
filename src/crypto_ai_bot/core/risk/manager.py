from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

from . import rules

def _get(d: Dict[str, Any], path: str, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def check(summary: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Агрегация правил риска → финальный вердикт.
    summary — снепшот контекста (PnL/экспозиция/маркет/время). НЕ делает IO.
    cfg — Settings.

    Возвращает: (ok: bool, reason: str) — первая причина отказа.
    Если хотите получить все причины — модифицируйте под возврат списка.
    """
    reasons: List[str] = []

    # --- TIME DRIFT ---
    if getattr(cfg, "ENABLE_RISK_TIME_DRIFT", True):
        drift_ms = _get(summary, "time.drift_ms", None)
        res = rules.check_time_drift(drift_ms, int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500)))
        if not res.ok:
            reasons.append(res.reason)

    # --- SPREAD ---
    if getattr(cfg, "ENABLE_RISK_SPREAD", True):
        spread = _get(summary, "market.spread_pct", None)
        res = rules.check_spread(spread, float(getattr(cfg, "MAX_SPREAD_PCT", 0.25)))
        if not res.ok:
            reasons.append(res.reason)

    # --- HOURS ---
    if getattr(cfg, "ENABLE_RISK_HOURS", True):
        res = rules.check_hours(int(getattr(cfg, "TRADING_START_HOUR", 0)),
                                int(getattr(cfg, "TRADING_END_HOUR", 24)))
        if not res.ok:
            reasons.append(res.reason)

    # --- DRAWDOWN ---
    if getattr(cfg, "ENABLE_RISK_DRAWDOWN", True):
        # пытаемся достать из разных мест summary
        dd = _get(summary, "risk.drawdown_pct", None)
        if dd is None:
            dd = _get(summary, "stats.drawdown_pct", None)
        res = rules.check_drawdown(dd, float(getattr(cfg, "MAX_DRAWDOWN_PCT", 5.0)))
        if not res.ok:
            reasons.append(res.reason)

    # --- SEQ LOSSES ---
    if getattr(cfg, "ENABLE_RISK_SEQ_LOSSES", True):
        seq = _get(summary, "stats.seq_losses", _get(summary, "risk.seq_losses", None))
        res = rules.check_seq_losses(seq, int(getattr(cfg, "MAX_SEQ_LOSSES", 3)))
        if not res.ok:
            reasons.append(res.reason)

    # --- EXPOSURE ---
    if getattr(cfg, "ENABLE_RISK_EXPOSURE", True):
        exp_pct = _get(summary, "exposure.pct", None)
        exp_usd = _get(summary, "exposure.usd", None)
        res = rules.check_max_exposure(exp_pct, exp_usd,
                                       getattr(cfg, "MAX_EXPOSURE_PCT", None),
                                       getattr(cfg, "MAX_EXPOSURE_USD", None))
        if not res.ok:
            reasons.append(res.reason)

    # Вердикт: если есть причины — блокируем первой
    if reasons:
        return (False, reasons[0])
    return (True, "")
