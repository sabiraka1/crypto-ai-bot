# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple


def _ok(code: str, **kw) -> Dict[str, Any]:
    return {"status": "ok", "code": code, **kw}


def _err(code: str, **kw) -> Dict[str, Any]:
    return {"status": "error", "code": code, **kw}


def _warn(code: str, **kw) -> Dict[str, Any]:
    return {"status": "warn", "code": code, **kw}


# ---------- TIME SYNC ----------

def check_time_sync(cfg: Any, http: Any) -> Dict[str, Any]:
    """
    Проверка рассинхронизации локальных часов с внешним временем.
    Использует utils.time_sync.measure_time_drift(cfg, http, urls, timeout).
    Ожидаем лимит в cfg.TIME_DRIFT_LIMIT_MS.
    """
    limit = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000) or 1000)
    urls = getattr(cfg, "TIME_DRIFT_URLS", None)

    try:
        from crypto_ai_bot.utils.time_sync import measure_time_drift
    except Exception:
        # если утиль недоступен — не блокируем, но подсвечиваем
        return _warn("time_sync_unknown", drift_ms=None, limit_ms=limit)

    try:
        drift = measure_time_drift(cfg, http, urls=urls, timeout=1.5)
    except Exception as e:
        return _warn("time_sync_check_failed", error=f"{type(e).__name__}: {e}", limit_ms=limit)

    if drift is None:
        return _warn("time_sync_unknown", drift_ms=None, limit_ms=limit)
    if int(drift) > limit:
        return _err("time_sync_drift_exceeded", drift_ms=int(drift), limit_ms=limit)
    return _ok("time_sync_ok", drift_ms=int(drift), limit_ms=limit)


# ---------- HOURS WINDOW ----------

def _parse_hours(spec: str) -> List[Tuple[int, int]]:
    """
    spec примеры:
      "0-24" (все часы),
      "9-17", "9-12,14-18"
    Возвращает список полузакрытых интервалов [start,end), где end может быть 24.
    """
    spec = (spec or "").strip()
    if not spec:
        return [(0, 24)]
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    out: List[Tuple[int, int]] = []
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            try:
                start = max(0, min(24, int(a)))
                end = max(0, min(24, int(b)))
            except Exception:
                continue
            if start == end == 0:
                continue
            if start < end:
                out.append((start, end))
            else:
                # если "22-2" — трактуем как два интервала: 22-24 и 0-2
                out.append((start, 24))
                out.append((0, end))
        else:
            try:
                h = max(0, min(23, int(p)))
                out.append((h, h + 1))
            except Exception:
                continue
    if not out:
        out = [(0, 24)]
    return out


def check_hours(cfg: Any, *, now_utc_hour: Optional[int] = None) -> Dict[str, Any]:
    """
    Разрешённые торговые часы (UTC) из cfg.RISK_HOURS_UTC.
    По умолчанию "0-24" (всегда).
    """
    spec = str(getattr(cfg, "RISK_HOURS_UTC", "0-24") or "0-24")
    intervals = _parse_hours(spec)
    h = int(now_utc_hour if now_utc_hour is not None else time.gmtime().tm_hour)
    allowed = any(start <= h < end for (start, end) in intervals)
    if allowed:
        return _ok("hours_ok", hour=h, spec=spec)
    return _err("hours_blocked", hour=h, spec=spec)


# ---------- SPREAD ----------

def check_spread(broker: Any, *, symbol: str, max_spread_bps: int) -> Dict[str, Any]:
    """
    Проверяет, что (ask-bid)/mid в б.п. не превышает порог.
    Требует broker.fetch_order_book(symbol) -> {"bids":[[px,qty],...], "asks":[[px,qty],...]}
    """
    try:
        ob = broker.fetch_order_book(symbol)
        bid = float(ob.get("bids", [[None]])[0][0]) if ob.get("bids") else None
        ask = float(ob.get("asks", [[None]])[0][0]) if ob.get("asks") else None
    except Exception as e:
        return _warn("spread_unknown", error=f"{type(e).__name__}: {e}", max_bps=int(max_spread_bps))

    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return _warn("spread_bad_orderbook", bid=bid, ask=ask, max_bps=int(max_spread_bps))

    mid = (bid + ask) / 2.0
    spread_bps = ((ask - bid) / mid) * 10_000.0
    if spread_bps > float(max_spread_bps):
        return _err("spread_too_wide", spread_bps=spread_bps, max_bps=int(max_spread_bps))
    return _ok("spread_ok", spread_bps=spread_bps, max_bps=int(max_spread_bps))


# ---------- MAX EXPOSURE (кол-во открытых позиций) ----------

def check_max_exposure(positions_repo: Any, *, max_positions: int) -> Dict[str, Any]:
    try:
        opens = positions_repo.get_open() or []
        cnt = int(len(opens))
    except Exception as e:
        return _warn("exposure_unknown", error=f"{type(e).__name__}: {e}", max_positions=int(max_positions))
    if cnt >= int(max_positions):
        return _err("exposure_limit_reached", open_count=cnt, max_positions=int(max_positions))
    return _ok("exposure_ok", open_count=cnt, max_positions=int(max_positions))


# ---------- DRAWDOWN / SEQUENCE LOSSES ----------

def _max_drawdown_from_pnls(pnls: List[float]) -> float:
    """
    pnls — список закрытых PnL (в тех же единицах). Возвращает max DD в процентах от пика к впадине
    на кумулятивной кривой (если нулевой масштаб — 0).
    """
    if not pnls:
        return 0.0
    equity = []
    s = 0.0
    for x in pnls:
        try:
            s += float(x)
        except Exception:
            continue
        equity.append(s)

    if not equity:
        return 0.0

    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v)  # абсолютное падение
        if peak != 0:
            dd_pct = (dd / abs(peak)) * 100.0
        else:
            dd_pct = 0.0 if dd == 0 else 100.0
        if dd_pct > max_dd:
            max_dd = dd_pct
    return max_dd


def check_drawdown(trades_repo: Any, *, lookback_days: int, max_drawdown_pct: float) -> Dict[str, Any]:
    """
    Рассчитывает приблизительный max DD по закрытым сделкам за «окно» (по возможности).
    Предпочитает метод trades_repo.last_closed_pnls(N). Если недоступно — возвращает warn.
    """
    pnls: List[float] = []
    # эвристика: 1000 последних — обычно покрывает lookback
    try:
        if hasattr(trades_repo, "last_closed_pnls"):
            pnls = [float(x) for x in (trades_repo.last_closed_pnls(1000) or []) if x is not None]  # type: ignore
        else:
            return _warn("drawdown_unknown", reason="no_last_closed_pnls", lookback_days=int(lookback_days))
    except Exception as e:
        return _warn("drawdown_unknown", error=f"{type(e).__name__}: {e}", lookback_days=int(lookback_days))

    dd = _max_drawdown_from_pnls(pnls)
    if dd > float(max_drawdown_pct):
        return _err("drawdown_exceeded", max_dd_pct=dd, limit_pct=float(max_drawdown_pct))
    return _ok("drawdown_ok", max_dd_pct=dd, limit_pct=float(max_drawdown_pct))


def check_sequence_losses(trades_repo: Any, *, window: int, max_losses: int) -> Dict[str, Any]:
    """
    Проверяет число подряд идущих убыточных сделок на последнем окне.
    """
    vals: List[float] = []
    try:
        if hasattr(trades_repo, "last_closed_pnls"):
            vals = [float(x) for x in (trades_repo.last_closed_pnls(int(window) or 10) or []) if x is not None]  # type: ignore
        else:
            return _warn("seq_losses_unknown", reason="no_last_closed_pnls", window=int(window))
    except Exception as e:
        return _warn("seq_losses_unknown", error=f"{type(e).__name__}: {e}", window=int(window))

    # считаем последние подряд «<0»
    seq = 0
    for p in reversed(vals):
        if p < 0:
            seq += 1
        else:
            break

    if seq >= int(max_losses):
        return _err("seq_losses_exceeded", consecutive_losses=seq, limit=int(max_losses))
    return _ok("seq_losses_ok", consecutive_losses=seq, limit=int(max_losses))
