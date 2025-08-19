from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple


Result = Dict[str, Any]


def _ok() -> Result:
    return {"ok": True, "code": "ok", "details": {}}


def _fail(code: str, **details) -> Result:
    return {"ok": False, "code": code, "details": details}


def _now_ms() -> int:
    return int(time.time() * 1000)


# -----------------------
# 1) ВРЕМЯ / СИНХРОНИЗАЦИЯ
# -----------------------

def check_time_sync(settings: Any, *, broker: Any = None, max_drift_ms: Optional[int] = None) -> Result:
    """
    Проверка рассинхронизации часов:
      - Если биржа поддерживает fetch_time → сверяемся по ней
      - Иначе — пропускаем (ok)
    """
    drift_limit = int(max_drift_ms if max_drift_ms is not None else getattr(settings, "MAX_TIME_DRIFT_MS", 15_000))
    try:
        if broker and hasattr(getattr(broker, "ccxt", broker), "fetch_time"):
            ex_now = broker.ccxt.fetch_time()  # ms (не всеми биржами поддерживается)
            if ex_now:
                drift = abs(_now_ms() - int(ex_now))
                if drift > drift_limit:
                    return _fail("time_drift", drift_ms=int(drift), limit_ms=drift_limit)
        return _ok()
    except Exception as e:
        # Неподдерживаемо/временный сбой — не блокируем торговлю
        return _ok()


# -----------------------
# 2) ЧАСЫ ТОРГОВ (UTC)
# -----------------------

def _parse_hours(text: str) -> Sequence[Tuple[int, int]]:
    """
    "00:00-23:59" | "09:30-16:00,18:00-20:00"
    Возвращает список пар (start_minutes, end_minutes)
    """
    spans = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            a, b = part.split("-", 1)
            h1, m1 = [int(x) for x in a.split(":")]
            h2, m2 = [int(x) for x in b.split(":")]
            spans.append((h1 * 60 + m1, h2 * 60 + m2))
        except Exception:
            continue
    return spans or [(0, 24 * 60 - 1)]


def check_hours(settings: Any) -> Result:
    """
    Разрешённые торги по UTC окнам.
    ENV: RISK_HOURS_UTC="00:00-23:59" (по умолчанию — 24/7)
    """
    cfg = str(getattr(settings, "RISK_HOURS_UTC", "00:00-23:59"))
    spans = _parse_hours(cfg)
    now = datetime.now(timezone.utc)
    minutes = now.hour * 60 + now.minute
    for a, b in spans:
        if a <= minutes <= b:
            return _ok()
    return _fail("trading_closed_utc", now_utc=now.isoformat(), allowed=cfg)


# -----------------------
# 3) СПРЕД
# -----------------------

def check_spread(settings: Any, *, broker: Any, symbol: str) -> Result:
    """
    Проверка ширины спреда в bps.
    ENV: MAX_SPREAD_BPS (по умолчанию 25)
    """
    limit_bps = float(getattr(settings, "MAX_SPREAD_BPS", 25))
    try:
        t = broker.fetch_ticker(symbol) or {}
        bid = float(t.get("bid") or 0.0)
        ask = float(t.get("ask") or 0.0)
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            spread_bps = abs(ask - bid) / mid * 10_000
            if spread_bps > limit_bps:
                return _fail("spread_too_wide", spread_bps=spread_bps, limit_bps=limit_bps)
        return _ok()
    except Exception as e:
        # Если нет тиков — безопаснее не торговать
        return _fail("no_ticker")


# -----------------------
# 4) ЛИМИТЫ ПОЗИЦИЙ / ЭКСПОЗИЦИЯ
# -----------------------

def check_max_exposure(
    settings: Any,
    *,
    positions_repo: Any,
    symbol: Optional[str] = None
) -> Result:
    """
    Проверяет:
      - нет ли открытого лонга по symbol (для long-only)
      - глобальный лимит количества одновременных позиций
    """
    max_positions = int(getattr(settings, "RISK_MAX_POSITIONS", 1))
    try:
        opens = positions_repo.get_open() or []
        if symbol:
            for r in opens:
                if str(r.get("symbol")) == symbol and float(r.get("qty") or 0.0) > 0:
                    return _fail("concurrent_position_blocked", symbol=symbol)
        if len(opens) >= max_positions:
            return _fail("max_positions_exceeded", open=len(opens), limit=max_positions)
        return _ok()
    except Exception as e:
        # если не можем проверить — блокируем
        return _fail("positions_check_failed")


# -----------------------
# 5) DRAWDOWN
# -----------------------

def _realized_pnl_pct_since(
    trades_repo: Any,
    *,
    since_ms: int
) -> float:
    """
    Находит реализованный PnL % с момента since_ms.
    Ожидает от трейд-репо метод realized_pnl_since_ms(since_ms) → (pnl_abs, basis_abs)
    где basis_abs — суммарная база (например, затраты в quote).
    Если basis_abs==0 — возвращаем 0.
    """
    try:
        pnl_abs, basis_abs = trades_repo.realized_pnl_since_ms(since_ms)
        if basis_abs and abs(basis_abs) > 1e-9:
            return float(pnl_abs) / float(basis_abs) * 100.0
        return 0.0
    except Exception:
        return 0.0


def check_drawdown(
    settings: Any,
    *,
    trades_repo: Any,
    lookback_days: Optional[int] = None
) -> Result:
    """
    Блокировка торгов при превышении реализованной просадки за окно.
    ENV:
      RISK_DRAWDOWN_LOOKBACK_DAYS (по умолчанию 7)
      RISK_MAX_DRAWDOWN_PCT      (по умолчанию 10.0)
    """
    days = int(lookback_days if lookback_days is not None else getattr(settings, "RISK_DRAWDOWN_LOOKBACK_DAYS", 7))
    limit_pct = float(getattr(settings, "RISK_MAX_DRAWDOWN_PCT", 10.0))
    since_ms = _now_ms() - days * 24 * 3600 * 1000
    pnl_pct = _realized_pnl_pct_since(trades_repo, since_ms=since_ms)
    # drawdown — когда pnl_pct отрицателен по модулю больше лимита
    if pnl_pct < 0 and abs(pnl_pct) >= limit_pct:
        return _fail("drawdown_limit", pnl_pct=float(pnl_pct), limit_pct=limit_pct, days=days)
    return _ok()


# -----------------------
# 6) ПОСЛЕДОВАТЕЛЬНЫЕ УБЫТКИ
# -----------------------

def check_sequence_losses(
    settings: Any,
    *,
    trades_repo: Any,
    max_losses: Optional[int] = None
) -> Result:
    """
    Не даёт торговать, если подряд было N убыточных сделок.
    ENV: RISK_MAX_LOSSES (по умолчанию 3)
    trades_repo должен уметь вернуть последние закрытые сделки с PnL.
    """
    limit = int(max_losses if max_losses is not None else getattr(settings, "RISK_MAX_LOSSES", 3))
    if limit <= 0:
        return _ok()
    try:
        rows = (trades_repo.get_last_closed(n=limit) or [])[:limit]
        if len(rows) < limit:
            return _ok()
        # считаем лузером сделку с pnl < 0
        for r in rows:
            pnl = float(r.get("pnl") or 0.0)
            if pnl >= 0:
                return _ok()
        # все limit подряд — лузеры
        return _fail("loss_streak", losses=limit)
    except Exception:
        # не можем проверить — лучше блокировать
        return _fail("loss_streak_check_failed")
