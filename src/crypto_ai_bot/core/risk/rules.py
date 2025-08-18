# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional


# ----------------- helpers -----------------

def _ok(code: str, **kw) -> Dict[str, Any]:
    return {"status": "ok", "code": code, **kw}

def _err(code: str, **kw) -> Dict[str, Any]:
    return {"status": "error", "code": code, **kw}

def _warn(code: str, **kw) -> Dict[str, Any]:
    return {"status": "warn", "code": code, **kw}


def _best_bid_ask(order_book: Dict[str, Any]) -> tuple[float, float]:
    try:
        bid = float((order_book.get("bids") or [[0, 0]])[0][0])
    except Exception:
        bid = 0.0
    try:
        ask = float((order_book.get("asks") or [[0, 0]])[0][0])
    except Exception:
        ask = 0.0
    return (bid, ask)


def _now_utc_hour() -> int:
    return int(time.gmtime().tm_hour)


def _parse_hours(spec: str) -> List[tuple[int, int]]:
    """
    Поддерживает:
      "0-24"        → [(0,24)]
      "9-17,20-22"  → [(9,17),(20,22)]
      "10"          → [(10,11)]
    Левая граница включительно, правая - исключается (как в range()).
    """
    out: List[tuple[int,int]] = []
    if not spec:
        return [(0,24)]
    for chunk in str(spec).split(","):
        s = chunk.strip()
        if not s:
            continue
        if "-" in s:
            a,b = s.split("-",1)
            try:
                lo = max(0, min(24, int(a)))
                hi = max(0, min(24, int(b)))
                if hi <= lo:  # защитимся
                    hi = min(24, lo+1)
                out.append((lo,hi))
            except Exception:
                continue
        else:
            try:
                h = max(0, min(24, int(s)))
                out.append((h, min(24, h+1)))
            except Exception:
                continue
    return out or [(0,24)]


def _in_hours(hours: List[tuple[int,int]], h: int) -> bool:
    for lo, hi in hours:
        if lo <= h < hi:
            return True
    return False


def _consecutive_losses(pnls: List[float]) -> int:
    cur = best = 0
    for p in pnls:
        if p < 0:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _equity_curve(pnls: List[float]) -> List[float]:
    eq, s = [], 0.0
    for p in pnls:
        try:
            s += float(p)
        except Exception:
            continue
        eq.append(s)
    return eq


def _max_drawdown_pct_from_equity(eq: List[float]) -> float:
    if not eq:
        return 0.0
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        if v > peak:
            peak = v
        dd = peak - v
        if peak != 0:
            mdd = max(mdd, (dd / abs(peak)) * 100.0)
    return float(mdd)


# Экспортируем ф-цию для переиспользования в бэктесте
def _max_drawdown_from_pnls(pnls: List[float]) -> float:
    return _max_drawdown_pct_from_equity(_equity_curve(pnls))


# ----------------- rules -----------------

def check_time_sync(cfg: Any, http: Any) -> Dict[str, Any]:
    """
    Измеряет абсолютный дрейф времени в миллисекундах.
    ОК, если drift_ms <= TIME_DRIFT_LIMIT_MS.
    """
    limit = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000) or 1000)
    try:
        from crypto_ai_bot.utils.time_sync import measure_time_drift
    except Exception:
        return _warn("time_sync_unavailable")

    try:
        urls = getattr(cfg, "TIME_DRIFT_URLS", None)
        timeout = float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0) or 2.0)
        drift_ms = measure_time_drift(cfg=cfg, http=http, urls=urls, timeout=timeout)
        if drift_ms is None:
            return _warn("time_sync_indeterminate")
        if drift_ms <= limit:
            return _ok("time_sync_ok", drift_ms=int(drift_ms))
        return _err("time_sync_drift_too_high", drift_ms=int(drift_ms), limit_ms=int(limit))
    except Exception as e:
        return _warn("time_sync_failed", error=f"{type(e).__name__}: {e}")


def check_hours(cfg: Any, now_utc_hour: Optional[int] = None) -> Dict[str, Any]:
    spec = str(getattr(cfg, "RISK_HOURS_UTC", "0-24") or "0-24")
    h = _now_utc_hour() if now_utc_hour is None else int(now_utc_hour)
    hours = _parse_hours(spec)
    if _in_hours(hours, h):
        return _ok("hours_ok", hour=h, spec=spec)
    return _err("hours_blocked", hour=h, spec=spec)


def check_spread(broker: Any, *, symbol: str, max_spread_bps: int) -> Dict[str, Any]:
    """
    Считает спред по top-of-book в б.п.: (ask - bid) / mid * 10_000
    """
    try:
        ob = broker.fetch_order_book(symbol)
    except Exception as e:
        return _warn("order_book_unavailable", error=f"{type(e).__name__}: {e}")

    bid, ask = _best_bid_ask(ob)
    if bid <= 0 or ask <= 0 or ask <= bid:
        return _warn("order_book_invalid", bid=bid, ask=ask)
    mid = 0.5 * (bid + ask)
    bps = (ask - bid) / mid * 10_000.0
    if bps <= float(max_spread_bps):
        return _ok("spread_ok", spread_bps=float(bps))
    return _err("spread_too_wide", spread_bps=float(bps), limit_bps=float(max_spread_bps))


def check_max_exposure(positions_repo: Any, *, max_positions: int) -> Dict[str, Any]:
    try:
        open_positions = positions_repo.get_open() or []
        cnt = len(open_positions)
    except Exception as e:
        return _warn("positions_unavailable", error=f"{type(e).__name__}: {e}")
    if cnt < int(max_positions):
        return _ok("exposure_ok", open_positions=cnt, limit=max_positions)
    return _err("exposure_limit_reached", open_positions=cnt, limit=max_positions)


def check_drawdown(trades_repo: Any, *, lookback_days: int, max_drawdown_pct: float) -> Dict[str, Any]:
    """
    Оцениваем DD по последним закрытым PnL (историю дней учитываем эвристикой — репозиторий может игнорировать)
    """
    try:
        if hasattr(trades_repo, "last_closed_pnls"):
            pnls = [float(x) for x in (trades_repo.last_closed_pnls(100000) or []) if x is not None]  # type: ignore
        else:
            pnls = []
    except Exception as e:
        return _warn("trades_unavailable", error=f"{type(e).__name__}: {e}")

    mdd = _max_drawdown_from_pnls(pnls)
    if mdd <= float(max_drawdown_pct):
        return _ok("drawdown_ok", mdd_pct=float(mdd))
    return _err("drawdown_exceeded", mdd_pct=float(mdd), limit_pct=float(max_drawdown_pct))


def check_sequence_losses(trades_repo: Any, *, window: int, max_losses: int) -> Dict[str, Any]:
    try:
        if hasattr(trades_repo, "last_closed_pnls"):
            pnls = [float(x) for x in (trades_repo.last_closed_pnls(max(1000, window)) or []) if x is not None]  # type: ignore
        else:
            pnls = []
    except Exception as e:
        return _warn("trades_unavailable", error=f"{type(e).__name__}: {e}")

    tail = pnls[-int(window):] if window > 0 else pnls
    seq = _consecutive_losses(tail)
    if seq <= int(max_losses):
        return _ok("seq_losses_ok", seq=int(seq))
    return _err("seq_losses_exceeded", seq=int(seq), limit=int(max_losses))
