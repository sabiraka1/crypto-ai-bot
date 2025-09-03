from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_ai_bot.utils.decimal import dec

# Константа для дефолтного значения B008
_DEFAULT_KELLY_CAP = dec("0.5")


@dataclass(frozen=True)
class SizeConstraints:
    """
    Ограничения размера позиции в котируемой валюте.
    Все поля опциональны: если None или 0 — ограничение не применяется.
    """

    max_quote_pct: Decimal | None = None  # доля от доступного баланса, например 0.1 (=10%)
    min_quote: Decimal | None = None  # минимальная сумма в котируемой
    max_quote: Decimal | None = None  # абсолютный потолок в котируемой


def _clamp(v: Decimal, *, min_v: Decimal | None, max_v: Decimal | None) -> Decimal:
    if min_v is not None and v < min_v:
        v = min_v
    if max_v is not None and v > max_v:
        v = max_v
    return v


def fixed_quote_amount(
    *, fixed: Decimal, constraints: SizeConstraints | None, free_quote_balance: Decimal | None = None
) -> Decimal:
    """
    Жёстко заданная сумма (например, FIXED_AMOUNT).
    Учитываем ограничения и (опционально) max_quote_pct от доступного free.
    """
    v = dec(str(fixed or 0))
    if constraints and constraints.max_quote_pct and free_quote_balance:
        cap = free_quote_balance * constraints.max_quote_pct
        if v > cap:
            v = cap
    if constraints:
        v = _clamp(v, min_v=constraints.min_quote, max_v=constraints.max_quote)
    return max(v, dec("0"))


def fixed_fractional(
    *, free_quote_balance: Decimal, fraction: Decimal, constraints: SizeConstraints | None
) -> Decimal:
    """
    Доля от доступного баланса (например, 5%).
    """
    f = dec(str(fraction or 0))
    v = free_quote_balance * f
    if constraints:
        # применим max_quote_pct, если задан — берём минимум из двух ограничителей
        if constraints.max_quote_pct and free_quote_balance:
            v = min(v, free_quote_balance * constraints.max_quote_pct)
        v = _clamp(v, min_v=constraints.min_quote, max_v=constraints.max_quote)
    return max(v, dec("0"))


def volatility_target_size(
    *,
    free_quote_balance: Decimal,
    market_vol_pct: Decimal,  # волатильность рынка в процентах (например, 1.2)
    target_portfolio_vol_pct: Decimal,  # целевая портфельная вола в процентах (например, 0.5)
    base_fraction: Decimal,  # базовая доля, напр. 0.05
    constraints: SizeConstraints | None,
) -> Decimal:
    """
    Простая схема «target volatility»: чем выше вола рынка — тем меньше размер.
    v = free * base_fraction * (target_vol / max(market_vol, eps))
    """
    eps = dec("0.0001")
    mv = max(dec(str(market_vol_pct or 0)), eps)
    tv = dec(str(target_portfolio_vol_pct or 0))
    base = free_quote_balance * dec(str(base_fraction or 0))
    v = base * (tv / mv) if tv > 0 else base

    if constraints:
        if constraints.max_quote_pct and free_quote_balance:
            v = min(v, free_quote_balance * constraints.max_quote_pct)
        v = _clamp(v, min_v=constraints.min_quote, max_v=constraints.max_quote)
    return max(v, dec("0"))


def naive_kelly(
    win_rate: Decimal, avg_win_pct: Decimal, avg_loss_pct: Decimal, cap: Decimal | None = None
) -> Decimal:
    """
    Наивная Kelly по ожиданию (%): f* = win_rate/avg_loss - (1 - win_rate)/avg_win
    Здесь работаем в долях на сделку, ограничиваем cap (по умолчанию 50%).
    """
    if cap is None:
        cap = _DEFAULT_KELLY_CAP

    w = dec(str(win_rate or 0))
    aw = dec(str(avg_win_pct or 0)) / dec("100")
    al = dec(str(avg_loss_pct or 0)) / dec("100")
    if aw <= 0 or al <= 0:
        return dec("0")
    # Простейшая аппроксимация Kelly — используйте аккуратно
    edge = (w * aw) - ((dec("1") - w) * al)
    var = (w * aw * aw) + ((dec("1") - w) * al * al)
    if var <= 0:
        return dec("0")
    f = edge / var
    f = max(dec("0"), min(f, dec(str(cap))))
    return f


def kelly_sized_quote(
    *,
    free_quote_balance: Decimal,
    win_rate: Decimal,
    avg_win_pct: Decimal,
    avg_loss_pct: Decimal,
    base_fraction: Decimal,
    constraints: SizeConstraints | None,
) -> Decimal:
    """
    Конвертируем Kelly-долю в котируемую сумму с ограничением базовой фракцией.
    """
    k = naive_kelly(win_rate, avg_win_pct, avg_loss_pct)
    f = min(k, dec(str(base_fraction or 0)))
    v = free_quote_balance * f
    if constraints:
        if constraints.max_quote_pct and free_quote_balance:
            v = min(v, free_quote_balance * constraints.max_quote_pct)
        v = _clamp(v, min_v=constraints.min_quote, max_v=constraints.max_quote)
    return max(v, dec("0"))
