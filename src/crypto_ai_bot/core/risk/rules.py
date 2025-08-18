# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal

from crypto_ai_bot.utils import metrics


CheckResult = Tuple[bool, str, Dict[str, Any]]  # (ok, code, details)


def _ok(code: str, **details: Any) -> CheckResult:
    return True, code, details


def _bad(code: str, **details: Any) -> CheckResult:
    return False, code, details


# ---------- helpers ----------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_hours_spec(spec: str) -> List[Tuple[int, int]]:
    """
    Парсер "9-17,20-22" → [(9,17),(20,22)] в часах UTC.
    Концы интервалов включительно.
    """
    out: List[Tuple[int, int]] = []
    if not spec:
        return [(0, 24)]
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            try:
                A = max(0, min(24, int(a)))
                B = max(0, min(24, int(b)))
                if A <= B:
                    out.append((A, B))
            except Exception:
                continue
        else:
            try:
                h = max(0, min(24, int(p)))
                out.append((h, h))
            except Exception:
                continue
    return out or [(0, 24)]


def _hour_allowed(utc_hour: int, ranges: List[Tuple[int, int]]) -> bool:
    for a, b in ranges:
        if a <= utc_hour <= b:
            return True
    return False


# ---------- правила ----------

def check_time_sync(cfg: Any, http: Any) -> CheckResult:
    """
    Проверка дрейфа времени относительно внешних источников.
    ОК, если |drift_ms| <= TIME_DRIFT_LIMIT_MS.
    """
    try:
        from crypto_ai_bot.utils.time_sync import measure_time_drift  # мягко
    except Exception:
        return _ok("time_sync_unavailable", used_urls=[], drift_ms=None, limit_ms=None)

    urls = getattr(cfg, "TIME_DRIFT_URLS", None) or []
    limit = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000) or 1000)

    drift_ms = measure_time_drift(cfg, http, urls=urls, timeout=1.5)
    if drift_ms is None:
        return _ok("time_sync_unknown", used_urls=urls, drift_ms=None, limit_ms=limit)

    ok = abs(int(drift_ms)) <= limit
    if ok:
        return _ok("time_sync_ok", drift_ms=int(drift_ms), limit_ms=limit, used_urls=urls)
    return _bad("time_sync_drift_exceeded", drift_ms=int(drift_ms), limit_ms=limit, used_urls=urls)


def check_spread(broker: Any, symbol: str, *, max_spread_bps: Optional[float] = None) -> CheckResult:
    """
    Расчёт спреда по best bid/ask:
      spread_bps = (ask - bid)/mid * 10_000
    """
    try:
        ob = broker.fetch_order_book(symbol, limit=5)
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        bid = float(bids[0][0]) if bids else None
        ask = float(asks[0][0]) if asks else None
    except Exception as e:
        return _ok("spread_unknown", error=f"{type(e).__name__}: {e}")

    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return _ok("spread_unknown", bid=bid, ask=ask)

    mid = (ask + bid) / 2.0
    spread_bps = ((ask - bid) / mid) * 10_000.0
    limit = float(max_spread_bps if max_spread_bps is not None else 25.0)  # дефолт

    if spread_bps <= limit:
        return _ok("spread_ok", bid=bid, ask=ask, spread_bps=spread_bps, limit_bps=limit)
    return _bad("spread_too_wide", bid=bid, ask=ask, spread_bps=spread_bps, limit_bps=limit)


def check_hours(cfg: Any, *, now_utc: Optional[datetime] = None) -> CheckResult:
    """
    Разрешённые часы по UTC. Формат ENV:
      RISK_HOURS_UTC="9-17,20-22" (включительно)
    По умолчанию — 0-24 (всегда разрешено).
    """
    spec = str(getattr(cfg, "RISK_HOURS_UTC", "") or "").strip()
    ranges = _parse_hours_spec(spec)
    now = now_utc or _now_utc()
    hour = int(now.hour)
    if _hour_allowed(hour, ranges):
        return _ok("hours_ok", hour=hour, ranges=ranges)
    return _bad("hours_blocked", hour=hour, ranges=ranges)


def check_drawdown(trades_repo: Any, *, lookback_days: Optional[int] = None, max_drawdown_pct: Optional[float] = None) -> CheckResult:
    """
    Используем реализованный PnL% за окно: get_realized_pnl(days).
    Если PnL < -max_drawdown_pct → блок.
    """
    days = int(lookback_days if lookback_days is not None else 7)
    limit = float(max_drawdown_pct if max_drawdown_pct is not None else 10.0)  # 10% по умолчанию

    try:
        pnl_pct = float(trades_repo.get_realized_pnl(days))  # может не существовать → исключение
    except Exception:
        return _ok("drawdown_unknown", days=days)

    if pnl_pct >= -limit:
        return _ok("drawdown_ok", pnl_pct=pnl_pct, limit_pct=limit)
    return _bad("drawdown_exceeded", pnl_pct=pnl_pct, limit_pct=limit)


def check_sequence_losses(trades_repo: Any, *, window: Optional[int] = None, max_losses: Optional[int] = None) -> CheckResult:
    """
    Последовательность убыточных закрытий по FIFO-модели (best-effort).
    Если хвост подряд из >= max_losses отрицательных PnL% → блок.
    """
    win = int(window if window is not None else 3)
    cap = int(max_losses if max_losses is not None else 3)
    if win <= 0 or cap <= 0:
        return _ok("seq_losses_disabled")

    try:
        series = list(trades_repo.last_closed_pnls(win))
    except Exception:
        return _ok("seq_losses_unknown", window=win)

    # считаем хвост подряд
    tail_losses = 0
    for v in reversed(series):
        if v is not None and float(v) < 0.0:
            tail_losses += 1
        else:
            break

    if tail_losses >= cap:
        return _bad("seq_losses_exceeded", window=win, max_losses=cap, tail_losses=tail_losses, series=series)
    return _ok("seq_losses_ok", window=win, max_losses=cap, tail_losses=tail_losses, series=series)


def check_max_exposure(positions_repo: Any, *, max_positions: Optional[int] = None) -> CheckResult:
    """
    Грубая ограничивалка по количеству открытых позиций.
    """
    lim = int(max_positions if max_positions is not None else 1)
    if lim <= 0:
        return _ok("exposure_disabled")

    try:
        open_positions = positions_repo.get_open() or []
        cnt = len(open_positions)
    except Exception:
        # совместимость, если интерфейс другой
        try:
            cnt = int(positions_repo.count_open())
        except Exception:
            return _ok("exposure_unknown")

    if cnt < lim:
        return _ok("exposure_ok", open_positions=cnt, limit=lim)
    return _bad("exposure_exceeded", open_positions=cnt, limit=lim)
