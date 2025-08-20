# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

"""
Единый набор риск-правил, без внешних зависимостей на core/* кроме репозиториев и брокера,
с гибкой сигнатурой (принимаем **kwargs, чтобы не падать от дополнительных аргументов).
Все функции возвращают словарь вида:
  {"ok": True}  или  {"ok": False, "reason": "<код>", "details": {...}}
"""

from typing import Any, Dict, Optional
from decimal import Decimal, InvalidOperation

from crypto_ai_bot.utils.time import now_ms


# ---------- ВСПОМОГАТЕЛЬНОЕ ----------

def _to_decimal(x: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if isinstance(x, Decimal):
            return x
        return Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError):
        return default


# ---------- БАЗОВЫЕ ПРАВИЛА ----------

def check_time_sync(*, settings, time_source_ms: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    """
    Если задан MAX_TIME_DRIFT_MS > 0 и предоставлен внешний time_source_ms,
    проверяем абсолютный дрейф. Иначе пропускаем (ok=True).
    """
    thresh = int(getattr(settings, "MAX_TIME_DRIFT_MS", 0) or 0)
    if thresh <= 0 or time_source_ms is None:
        return {"ok": True}
    drift = abs(now_ms() - int(time_source_ms))
    if drift > thresh:
        return {"ok": False, "reason": "time_drift", "details": {"drift_ms": drift, "limit_ms": thresh}}
    return {"ok": True}


def check_hours(*, settings, now_utc_ms: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    """
    Разрешённые торговые окна по UTC.
    Формат переменной settings.RISK_HOURS_UTC (строка):
      - "24/7" (по умолчанию — всегда)
      - "HH:MM-HH:MM" (одно окно)
      - "HH:MM-HH:MM,HH:MM-HH:MM" (несколько)
    """
    window = (getattr(settings, "RISK_HOURS_UTC", "") or "").strip()
    if not window or window.upper() == "24/7":
        return {"ok": True}

    import datetime as dt
    now_ms_local = now_utc_ms or now_ms()
    t = dt.datetime.utcfromtimestamp(now_ms_local / 1000.0).time()
    hhmm = t.hour * 60 + t.minute

    def _parse_pair(s: str) -> Optional[tuple[int, int]]:
        s = s.strip()
        if "-" not in s:
            return None
        a, b = s.split("-", 1)
        try:
            ah, am = map(int, a.split(":", 1))
            bh, bm = map(int, b.split(":", 1))
            return ah * 60 + am, bh * 60 + bm
        except Exception:
            return None

    parts = [p for p in window.split(",") if p.strip()]
    for p in parts:
        bounds = _parse_pair(p)
        if not bounds:
            continue
        a, b = bounds
        if a <= b:
            if a <= hhmm <= b:
                return {"ok": True}
        else:
            # окно через полночь
            if hhmm >= a or hhmm <= b:
                return {"ok": True}

    return {"ok": False, "reason": "hours_blocked", "details": {"RISK_HOURS_UTC": window, "now_hhmm": hhmm}}


def check_spread(*, broker, symbol: str, settings, **_: Any) -> Dict[str, Any]:
    """
    Контроль ширины спреда (bps). Для торгуемых маркет-ордеров не влезаем в неликвид.
    settings.MAX_SPREAD_BPS (int, например 50 = 0.50%)
    """
    limit_bps = int(getattr(settings, "MAX_SPREAD_BPS", 0) or 0)
    if limit_bps <= 0:
        return {"ok": True}
    try:
        t = broker.fetch_ticker(symbol)
        bid = float(t.get("bid") or 0.0)
        ask = float(t.get("ask") or 0.0)
        if bid <= 0 or ask <= 0:
            return {"ok": False, "reason": "no_quote", "details": {"bid": bid, "ask": ask}}
        mid = (bid + ask) / 2.0
        spread_bps = abs(ask - bid) / mid * 10000.0
        if spread_bps > limit_bps:
            return {"ok": False, "reason": "spread_too_wide", "details": {"spread_bps": spread_bps, "limit_bps": limit_bps}}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": "spread_check_error", "details": {"error": str(e)}}


def check_max_exposure(*, positions_repo, settings, symbol: str, **_: Any) -> Dict[str, Any]:
    """
    Лимит открытых лонгов (для long-only). Два уровня:
      - глобальный settings.RISK_MAX_POSITIONS (всего по всем символам)
      - запрет второго лонга по тому же символу
    """
    lim = int(getattr(settings, "RISK_MAX_POSITIONS", 1) or 1)
    try:
        # глобальный
        try:
            total_open = int(positions_repo.count_open())  # если есть такой метод
        except Exception:
            # fallback: пытаемся понять по всем позициям
            try:
                all_pos = positions_repo.list_all()  # [{'symbol': 'BTC/USDT', 'qty': '0.01', ...}, ...]
                total_open = sum(1 for p in all_pos if _to_decimal(p.get("qty")) > 0)
            except Exception:
                total_open = 0

        if total_open >= lim:
            return {"ok": False, "reason": "max_positions", "details": {"open": total_open, "limit": lim}}

        # по символу
        try:
            pos = positions_repo.get(symbol)
            qty = _to_decimal(pos.get("qty") if pos else 0)
            if qty > 0:
                return {"ok": False, "reason": "concurrent_long", "details": {"symbol": symbol, "qty": str(qty)}}
        except Exception:
            # если репо не поддерживает get(symbol), пропускаем
            pass

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": "exposure_check_error", "details": {"error": str(e)}}


def realized_pnl_since_ms(*, trades_repo, since_ms: int) -> Decimal:
    """
    Утилита для drawdown/daily loss. Если репозиторий не поддерживает —
    возвращаем 0.
    """
    try:
        return _to_decimal(trades_repo.realized_pnl_since_ms(since_ms))
    except Exception:
        return Decimal("0")


def check_drawdown(*, trades_repo, settings, window_ms: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    """
    Контроль просадки за окно.
    settings.RISK_MAX_DRAWDOWN_PCT (например, 10)
    settings.RISK_DRAWDOWN_WINDOW_MS (например, 7 дней)
    """
    limit_pct = _to_decimal(getattr(settings, "RISK_MAX_DRAWDOWN_PCT", 0))
    if limit_pct <= 0:
        return {"ok": True}
    win_ms = int(window_ms if window_ms is not None else int(getattr(settings, "RISK_DRAWDOWN_WINDOW_MS", 0) or 0))
    if win_ms <= 0:
        return {"ok": True}
    pnl = realized_pnl_since_ms(trades_repo=trades_repo, since_ms=now_ms() - win_ms)
    # pnl < 0 — убыток. Если |pnl| / notional_base > лимита — блок
    # Без полной эквити: считаем относительную просадку как % от абсолютного notional-эквивалента.
    # Базово: если pnl <= -limit_pct% от 1.0 «условной базы», трактуем как триггер.
    # (Уточни логику под свою модель капитала — здесь мягкая проверка.)
    if pnl < 0 and abs(pnl) >= (limit_pct / Decimal("100")):
        return {"ok": False, "reason": "drawdown_limit", "details": {"pnl": str(pnl), "limit_pct": str(limit_pct)}}
    return {"ok": True}


def check_sequence_losses(*, trades_repo, settings, **_: Any) -> Dict[str, Any]:
    """
    Последовательность убыточных сделок подряд.
    settings.RISK_MAX_LOSSES (например, 3)
    """
    max_losses = int(getattr(settings, "RISK_MAX_LOSSES", 0) or 0)
    if max_losses <= 0:
        return {"ok": True}
    try:
        # ожидается, что репо умеет last_losses_streak()
        streak = int(trades_repo.last_losses_streak())
        if streak >= max_losses:
            return {"ok": False, "reason": "loss_streak", "details": {"streak": streak, "limit": max_losses}}
        return {"ok": True}
    except Exception:
        # fallback: разрешаем
        return {"ok": True}


# ---------- СТАРЫЕ АЛИАСЫ ДЛЯ СОВМЕСТИМОСТИ ----------

def risk_concurrent_positions_blocked(*, positions_repo, symbol: str, **kwargs: Any) -> Dict[str, Any]:
    """Совместимость: алиас на check_max_exposure только по символу."""
    return check_max_exposure(positions_repo=positions_repo, settings=kwargs.get("settings"), symbol=symbol)


def risk_daily_loss_blocked(*, trades_repo, settings, **_: Any) -> Dict[str, Any]:
    """
    Если настроен дневной лимит убытка (%), проверяем реализацию за последние 24 часа.
    settings.RISK_DAILY_LOSS_PCT
    """
    limit_pct = _to_decimal(getattr(settings, "RISK_DAILY_LOSS_PCT", 0))
    if limit_pct <= 0:
        return {"ok": True}
    one_day_ms = 24 * 60 * 60 * 1000
    pnl = realized_pnl_since_ms(trades_repo=trades_repo, since_ms=now_ms() - one_day_ms)
    if pnl < 0 and abs(pnl) >= (limit_pct / Decimal("100")):
        return {"ok": False, "reason": "daily_loss_limit", "details": {"pnl": str(pnl), "limit_pct": str(limit_pct)}}
    return {"ok": True}
