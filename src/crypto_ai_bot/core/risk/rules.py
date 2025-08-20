# src/crypto_ai_bot/core/risk/rules.py
"""
Правила риск-менеджмента (long-only).

Все функции возвращают dict вида:
    {"ok": True}
или
    {"ok": False, "code": "<machine_code>", "reason": "<human text>", "details": {...}}

Сигнатуры выдержаны «широкими»: принимают **kwargs, чтобы не падать,
если вызывающая сторона передаёт больше аргументов (совместимость с существующим RM).
"""

from __future__ import annotations
from typing import Any, Dict, Optional
from datetime import datetime, timezone

# Унифицированный helper «текущее время в ms»
def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


# ---------- БАЗОВЫЕ ПОМОЩНИКИ ----------

def _ok() -> Dict[str, Any]:
    return {"ok": True}


def _blocked(code: str, reason: str, **details: Any) -> Dict[str, Any]:
    d = {"ok": False, "code": code, "reason": reason}
    if details:
        d["details"] = details
    return d


# ---------- ПРАВИЛА ----------

def check_time_sync(
    settings: Any,
    **_: Any,
) -> Dict[str, Any]:
    """
    Базовая проверка: если есть механизм сверки времени (NTP или биржа),
    здесь можно сравнивать «рассинхрон». Сейчас — пасс через конфиг.
    """
    max_drift_ms = int(getattr(settings, "RISK_MAX_TIME_DRIFT_MS", 60_000))
    # Если верхний уровень уже где-то измеряет drift и кладёт в settings, учитываем:
    drift_ms = int(getattr(settings, "LAST_MEASURED_DRIFT_MS", 0))
    if drift_ms > max_drift_ms:
        return _blocked("time_drift", f"Системные часы рассинхронизированы на {drift_ms}ms",
                        drift_ms=drift_ms, max_drift_ms=max_drift_ms)
    return _ok()


def check_hours(
    settings: Any,
    now_ms: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    Разрешённые торговые часы (UTC), например:
      RISK_HOURS_UTC = "00:00-23:59" (по умолчанию — разрешено всегда)
      или "07:00-20:00"
    """
    window = getattr(settings, "RISK_HOURS_UTC", "00:00-23:59")
    try:
        start_s, end_s = window.split("-")
        now = datetime.fromtimestamp((now_ms or _now_ms()) / 1000, tz=timezone.utc)
        now_m = now.hour * 60 + now.minute

        def parse(hhmm: str) -> int:
            hh, mm = map(int, hhmm.split(":"))
            return hh * 60 + mm

        start_m = parse(start_s)
        end_m = parse(end_s)

        allowed = start_m <= now_m <= end_m if start_m <= end_m else (now_m >= start_m or now_m <= end_m)
        if not allowed:
            return _blocked("blocked_hours", f"Вне торговых часов (UTC {start_s}-{end_s})",
                            now_utc=now.strftime("%H:%M"))
        return _ok()
    except Exception as e:  # не валим торговлю из-за неверного формата; просто пропускаем правило
        return _ok()


def check_spread(
    settings: Any,
    *,
    broker: Any,
    symbol: str,
    **_: Any,
) -> Dict[str, Any]:
    """
    Гард по спреду: если bid/ask отсутствуют — пропускаем; если есть — сравниваем bps с лимитом.
    """
    max_spread_bps = float(getattr(settings, "RISK_MAX_SPREAD_BPS", 50.0))  # 0.50%
    try:
        t = broker.fetch_ticker(symbol)
        bid = float(t.get("bid") or 0.0)
        ask = float(t.get("ask") or 0.0)
        if bid > 0.0 and ask > 0.0:
            mid = (bid + ask) / 2.0
            spread_bps = abs(ask - bid) / mid * 10_000.0
            if spread_bps > max_spread_bps:
                return _blocked("spread_too_wide", f"Широкий спред: {spread_bps:.1f}bps > {max_spread_bps}bps",
                                spread_bps=spread_bps, limit_bps=max_spread_bps)
    except Exception:
        # Лучшe «молчаливо разрешить», чем ломать исполнение при временном сбое тика
        pass
    return _ok()


def check_max_exposure(
    settings: Any,
    *,
    positions_repo: Any,
    symbol: str,
    **_: Any,
) -> Dict[str, Any]:
    """
    Не держать > N открытых лонгов одновременно (для multi-symbol режимов).
    Здесь: проверяем, что по этому symbol ещё нет открытого long.
    """
    max_positions = int(getattr(settings, "RISK_MAX_POSITIONS", 1))
    try:
        # предполагаем, что repo возвращает qty (float/Decimal) > 0 для открытого лонга
        pos = positions_repo.get(symbol=symbol)
        has_long = bool(pos and float(pos.get("qty", 0) or 0) > 0)
        if has_long or max_positions <= 0:
            return _blocked("concurrent_position_blocked", "По инструменту уже есть открытая long позиция",
                            existing_qty=float(pos.get("qty", 0)) if pos else 0.0)
    except Exception:
        pass
    return _ok()


def realized_pnl_since_ms(
    *,
    trades_repo: Any,
    since_ms: int,
    symbol: Optional[str] = None,
) -> float:
    """
    Вспомогательно: реализованный PnL (FIFO) с момента since_ms (ms).
    Ожидаем, что repo предоставит агрегирующий метод, иначе считаем консервативно 0.0.
    """
    if hasattr(trades_repo, "realized_pnl_since_ms"):
        try:
            return float(trades_repo.realized_pnl_since_ms(since_ms=since_ms, symbol=symbol) or 0.0)
        except Exception:
            return 0.0
    return 0.0


def check_drawdown(
    settings: Any,
    *,
    trades_repo: Any,
    symbol: Optional[str] = None,
    now_ms: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    Лимит просадки по реализованному PnL за окно RISK_DRAWDOWN_WINDOW_HOURS.
    Пример: за последние 168 часов (7 дней) PnL <= -RISK_MAX_DRAWDOWN_PCT * equity.
    Если нет репо эквити — считаем в «абсолюте» через USD-эквивалент позиции/настройки.
    """
    window_h = int(getattr(settings, "RISK_DRAWDOWN_WINDOW_HOURS", 168))
    max_dd_pct = float(getattr(settings, "RISK_MAX_DRAWDOWN_PCT", 10.0))  # 10%
    equity_usd = float(getattr(settings, "EQUITY_USD", 0.0)) or float(getattr(settings, "POSITION_SIZE_USD", 100.0)) * 10
    since = (now_ms or _now_ms()) - window_h * 3600 * 1000

    pnl = realized_pnl_since_ms(trades_repo=trades_repo, since_ms=since, symbol=symbol)
    if equity_usd <= 0:
        # Если непонятно, от чего считать, блок не включаем.
        return _ok()

    dd_pct = (pnl / equity_usd) * 100.0
    if dd_pct < 0 and abs(dd_pct) >= max_dd_pct:
        return _blocked("drawdown_exceeded",
                        f"Просадка {dd_pct:.2f}% превышает лимит {max_dd_pct:.2f}%",
                        pnl_usd=pnl, equity_usd=equity_usd, window_h=window_h)
    return _ok()


def check_sequence_losses(
    settings: Any,
    *,
    trades_repo: Any,
    symbol: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    Последовательные убыточные сделки. Если подряд >= лимита — блокируем.
    Требуется метод trades_repo.consecutive_losses(symbol: str|None) -> int, иначе пропускаем.
    """
    limit = int(getattr(settings, "RISK_MAX_CONSECUTIVE_LOSSES", 3))
    if limit <= 0:
        return _ok()
    try:
        if hasattr(trades_repo, "consecutive_losses"):
            n = int(trades_repo.consecutive_losses(symbol=symbol))
            if n >= limit:
                return _blocked("loss_streak", f"Серия убыточных сделок = {n} (лимит {limit})",
                                losses=n, limit=limit)
    except Exception:
        pass
    return _ok()


# Сохранены имена «старых» функций для обратной совместимости
def risk_concurrent_positions_blocked(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return check_max_exposure(*args, **kwargs)


def risk_daily_loss_blocked(
    settings: Any,
    *,
    trades_repo: Any,
    symbol: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    Пример простого дневного лимита убытков. Если нужен — используйте, иначе пусть остаётся no-op.
    """
    max_daily_loss = float(getattr(settings, "RISK_MAX_DAILY_LOSS_USD", 0.0))
    if max_daily_loss <= 0:
        return _ok()
    # Требуется метод repo.daily_realized_pnl(symbol) -> float. Если нет — пропускаем.
    if hasattr(trades_repo, "daily_realized_pnl"):
        try:
            pnl = float(trades_repo.daily_realized_pnl(symbol=symbol) or 0.0)
        except Exception:
            return _ok()
        if pnl < 0 and abs(pnl) >= max_daily_loss:
            return _blocked("daily_loss_limit", "Достигнут дневной лимит убытка",
                            pnl_usd=pnl, limit_usd=max_daily_loss)
    return _ok()
