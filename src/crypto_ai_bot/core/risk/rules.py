# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

"""
Чистые атомарные проверки риска.
Никаких вызовов брокера/БД/HTTP. Только числа из features и пороги из cfg.
Все времена — UTC.
"""

from datetime import datetime, time, timezone
from typing import Any, Dict, Tuple, Optional

from crypto_ai_bot.utils import time_sync as ts


def _cfg_float(cfg: Any, name: str, default: float) -> float:
    try:
        return float(getattr(cfg, name, default))
    except Exception:
        return float(default)


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    try:
        return int(getattr(cfg, name, default))
    except Exception:
        return int(default)


def _get(d: Dict[str, Any], *path: str, default: Optional[float] = None):
    cur: Any = d or {}
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


# ───────────────────────── базовые правила (атомарные) ────────────────────────

def check_time_sync(cfg: Any) -> Tuple[bool, str]:
    """
    Блокируем торговлю при слишком большом расхождении часов.
    Источник значения — utils.time_sync (обновляется оркестратором).
    """
    limit = _cfg_int(cfg, "TIME_DRIFT_MAX_MS", 1500)
    drift = ts.get_cached_drift_ms(0)
    if abs(drift) > limit:
        return False, f"time_drift_ms={drift}>limit={limit}"
    return True, "ok"


def check_spread(features: Dict[str, Any], cfg: Any) -> Tuple[bool, str]:
    """
    Проверка на максимальный спред (в % от mid).
    Берём готовый features.market.spread_pct, либо считаем из bid/ask, если доступны.
    """
    max_spread = _cfg_float(cfg, "MAX_SPREAD_PCT", 0.20)  # по умолчанию 0.20%
    mkt = features.get("market", {}) or {}

    sp = _get(features, "market", "spread_pct")
    if sp is None:
        bid = _get(features, "market", "bid")
        ask = _get(features, "market", "ask")
        if bid and ask and bid > 0 and ask > 0 and ask >= bid:
            mid = (float(bid) + float(ask)) / 2.0
            if mid > 0:
                sp = (float(ask) - float(bid)) / mid * 100.0

    if sp is None:
        # нет данных — считаем правило «не применимо»
        return True, "n/a"

    if float(sp) > max_spread:
        return False, f"spread_pct={sp:.4f}>max={max_spread:.4f}"
    return True, "ok"


def check_hours(cfg: Any, now_utc: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Торговые часы/дни. Все значения — UTC.
    Параметры:
      - TRADING_HOURS_START="HH:MM", TRADING_HOURS_END="HH:MM"
      - TRADING_DAYS="1,2,3,4,5"  (0=Mon..6=Sun). Если пусто — без ограничений.
      - TRADING_HOURS_ENABLED (bool-like), если False — не проверяем.
    Поддержка окна через полночь: например 22:00..02:00.
    """
    enabled = str(getattr(cfg, "TRADING_HOURS_ENABLED", "true")).lower() in ("1", "true", "yes", "on")
    if not enabled:
        return True, "disabled"

    start_s = str(getattr(cfg, "TRADING_HOURS_START", "") or "")
    end_s = str(getattr(cfg, "TRADING_HOURS_END", "") or "")
    days_s = str(getattr(cfg, "TRADING_DAYS", "") or "")

    if not start_s or not end_s:
        return True, "n/a"

    def _parse_hhmm(s: str) -> time:
        hh, mm = s.split(":")
        return time(int(hh), int(mm), tzinfo=timezone.utc)

    try:
        t_start = _parse_hhmm(start_s)
        t_end = _parse_hhmm(end_s)
    except Exception:
        return True, "n/a"

    now = now_utc or datetime.now(timezone.utc)
    cur_t = time(now.hour, now.minute, now.second, tzinfo=timezone.utc)
    cur_dow = now.weekday()  # 0..6

    if days_s.strip():
        try:
            allowed_days = {int(x.strip()) for x in days_s.split(",") if x.strip() != ""}
        except Exception:
            allowed_days = set(range(0, 7))
        if cur_dow not in allowed_days:
            return False, f"day={cur_dow} not in {sorted(allowed_days)}"

    if t_start <= t_end:
        ok = (cur_t >= t_start) and (cur_t <= t_end)
    else:
        # окно через полночь
        ok = (cur_t >= t_start) or (cur_t <= t_end)

    if not ok:
        return False, f"time={cur_t.isoformat()} not in {t_start.isoformat()}..{t_end.isoformat()}"
    return True, "ok"


def check_seq_losses(features: Dict[str, Any], cfg: Any) -> Tuple[bool, str]:
    """
    Последовательные убыточные сделки. Ожидаем, что upstream-процессы
    положили в features.risk.loss_streak актуальное значение (целое).
    """
    limit = _cfg_int(cfg, "MAX_SEQ_LOSSES", 3)
    streak = int(_get(features, "risk", "loss_streak", default=0) or 0)
    if streak >= limit > 0:
        return False, f"loss_streak={streak}>=max={limit}"
    return True, "ok"


def check_max_exposure(features: Dict[str, Any], cfg: Any) -> Tuple[bool, str]:
    """
    Максимальная совокупная экспозиция по счёту (%).
    Ожидаем features.risk.exposure_pct (float).
    """
    max_exp = _cfg_float(cfg, "MAX_EXPOSURE_PCT", 100.0)
    exp = _get(features, "risk", "exposure_pct", default=0.0)
    if exp is None:
        return True, "n/a"
    if float(exp) > max_exp:
        return False, f"exposure_pct={float(exp):.2f}>max={max_exp:.2f}"
    return True, "ok"


def check_drawdown(features: Dict[str, Any], cfg: Any) -> Tuple[bool, str]:
    """
    Суточная просадка (%) — блокируем при превышении порога.
    Ожидаем features.risk.dd_pct (float).
    """
    max_dd = _cfg_float(cfg, "MAX_DRAWDOWN_PCT", 5.0)
    dd = _get(features, "risk", "dd_pct", default=0.0)
    if dd is None:
        return True, "n/a"
    if float(dd) <= -abs(max_dd):  # dd обычно отрицательная величина
        return False, f"drawdown_pct={float(dd):.2f}<=-{abs(max_dd):.2f}"
    return True, "ok"
