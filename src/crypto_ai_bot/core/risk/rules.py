# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


def _utcnow() -> _dt.datetime:
    return _dt.datetime.utcnow().replace(tzinfo=_dt.timezone.utc)


def _safe_decimal(x: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return default


def check_spread(
    cfg: Any,
    broker: Any,
    symbol: str,
) -> Tuple[bool, str]:
    """
    Проверяем относительный спред bid/ask в б.п. (basis points).
    Лимит задаётся cfg.RISK_MAX_SPREAD_BPS (дефолт 15 б.п.).
    """
    limit_bps = int(getattr(cfg, "RISK_MAX_SPREAD_BPS", 15))
    if limit_bps <= 0:
        return True, "spread_disabled"

    best_bid = None
    best_ask = None

    # 1) пробуем ордербук
    try:
        ob = broker.fetch_order_book(symbol)
        if ob and ob.get("bids") and ob.get("asks"):
            best_bid = _safe_decimal(ob["bids"][0][0])
            best_ask = _safe_decimal(ob["asks"][0][0])
    except Exception:
        pass

    # 2) fallback — тикер
    if best_bid is None or best_ask is None:
        try:
            t = broker.fetch_ticker(symbol) or {}
            best_bid = best_bid or _safe_decimal(t.get("bid"))
            best_ask = best_ask or _safe_decimal(t.get("ask"))
        except Exception:
            pass

    if not best_bid or not best_ask or best_bid <= 0 or best_ask <= 0:
        # не можем оценить — не блокируем
        return True, "spread_unknown"

    mid = (best_bid + best_ask) / Decimal("2")
    spread = (best_ask - best_bid) / mid if mid > 0 else Decimal("0")
    spread_bps = int(spread * Decimal("10000"))

    if spread_bps > limit_bps:
        return False, f"spread_{spread_bps}bps_gt_{limit_bps}bps"
    return True, "ok"


def check_hours(cfg: Any) -> Tuple[bool, str]:
    """
    Ограничение времени торгов по часам UTC.
    cfg.RISK_ALLOWED_HOURS: строка вида "7-22" или "8,9,10,11,15" (по UTC).
    Если не задано — правило выключено.
    """
    hours_spec = getattr(cfg, "RISK_ALLOWED_HOURS", "").strip()
    if not hours_spec:
        return True, "hours_disabled"

    now_h = _utcnow().hour
    allowed: List[int] = []

    for chunk in hours_spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            try:
                a, b = int(a), int(b)
                if a <= b:
                    allowed.extend(list(range(a, b + 1)))
                else:
                    # диапазон через полуночь
                    allowed.extend(list(range(a, 24)) + list(range(0, b + 1)))
            except Exception:
                continue
        else:
            try:
                allowed.append(int(chunk))
            except Exception:
                continue

    if now_h in set(allowed):
        return True, "ok"
    return False, f"hour_utc_{now_h}_not_allowed"


def check_drawdown(
    cfg: Any,
    trades_repo: Any,
) -> Tuple[bool, str]:
    """
    Контроль максимально допустимой просадки по реализованному PnL.
    cfg.RISK_MAX_DRAWDOWN_PCT (дефолт 20.0) за окно cfg.RISK_MAX_DRAWDOWN_DAYS (дефолт 7).
    Реализация «лучшее усилие»: если в репозитории нет нужных методов — не блокируем.
    """
    max_dd_pct = float(getattr(cfg, "RISK_MAX_DRAWDOWN_PCT", 20.0))
    window_days = int(getattr(cfg, "RISK_MAX_DRAWDOWN_DAYS", 7))
    if max_dd_pct <= 0 or window_days <= 0:
        return True, "drawdown_disabled"

    # ожидаемые методы: trades_repo.get_realized_pnl(days: int) -> float
    try:
        pnl = float(trades_repo.get_realized_pnl(days=window_days))
    except Exception:
        return True, "drawdown_unknown"

    # упрощённо: если суммарный pnl ниже -max_dd_pct от «условной базы» (0 → блок не сработает)
    # Для практики лучше иметь «equity curve» и искать локальный максимум/минимум.
    if pnl < 0:
        # считаем в процентах от абсолютного значения убытков, имитируем «просадку»
        dd_pct = abs(pnl)  # если метод уже отдаёт % — ок
        if dd_pct > max_dd_pct:
            return False, f"drawdown_{dd_pct:.2f}%_gt_{max_dd_pct}%"
    return True, "ok"


def check_sequence_losses(
    cfg: Any,
    trades_repo: Any,
) -> Tuple[bool, str]:
    """
    Блок при серии убыточных сделок.
    cfg.RISK_MAX_CONSECUTIVE_LOSSES (дефолт 3).
    Ожидаемый метод: trades_repo.last_closed_pnls(n: int) -> List[float]
    """
    max_seq = int(getattr(cfg, "RISK_MAX_CONSECUTIVE_LOSSES", 3))
    if max_seq <= 0:
        return True, "seq_losses_disabled"

    try:
        pnls = trades_repo.last_closed_pnls(n=max_seq)
        if not isinstance(pnls, list) or not pnls:
            return True, "seq_losses_unknown"
        if all((float(x) < 0 for x in pnls)):
            return False, f"seq_losses_{len(pnls)}_ge_{max_seq}"
    except Exception:
        return True, "seq_losses_unknown"

    return True, "ok"


def check_max_exposure(
    cfg: Any,
    positions_repo: Any,
    broker: Any,
    side: str,
    symbol: str,
) -> Tuple[bool, str]:
    """
    Глобальный контроль «перегрева» портфеля.
    Минимально совместимая версия — ограничение числа открытых позиций.
    cfg.RISK_MAX_OPEN_POSITIONS (дефолт 3).
    Для sell ограничение снимаем (разгрузка).
    """
    if str(side).lower() == "sell":
        return True, "exposure_sell_ok"

    max_open = int(getattr(cfg, "RISK_MAX_OPEN_POSITIONS", 3))
    if max_open <= 0:
        return True, "exposure_disabled"

    try:
        open_list = positions_repo.get_open() or []
        # если позиция уже открыта по symbol — не считаем её как «новую»
        others = [p for p in open_list if str(p.get("symbol", "")).upper() != symbol.upper()]
        if len(others) >= max_open:
            return False, f"open_positions_{len(others)}_ge_{max_open}"
    except Exception:
        # если не можем посчитать — не блокируем
        return True, "exposure_unknown"

    return True, "ok"
