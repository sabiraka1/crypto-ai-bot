from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_ai_bot.utils.decimal import dec

# РљРѕРЅСЃС‚Р°РЅС‚Р° РґР»СЏ РґРµС„РѕР»С‚РЅРѕРіРѕ Р·РЅР°С‡РµРЅРёСЏ B008
_DEFAULT_KELLY_CAP = dec("0.5")


@dataclass(frozen=True)
class SizeConstraints:
    """
    РћРіСЂР°РЅРёС‡РµРЅРёСЏ СЂР°Р·РјРµСЂР° РїРѕР·РёС†РёРё РІ РєРѕС‚РёСЂСѓРµРјРѕР№ РІР°Р»СЋС‚Рµ.
    Р’СЃРµ РїРѕР»СЏ РѕРїС†РёРѕРЅР°Р»СЊРЅС‹: РµСЃР»Рё None РёР»Рё 0 вЂ” РѕРіСЂР°РЅРёС‡РµРЅРёРµ РЅРµ РїСЂРёРјРµРЅСЏРµС‚СЃСЏ.
    """

    max_quote_pct: Decimal | None = None  # РґРѕР»СЏ РѕС‚ РґРѕСЃС‚СѓРїРЅРѕРіРѕ Р±Р°Р»Р°РЅСЃР°, РЅР°РїСЂРёРјРµСЂ 0.1 (=10%)
    min_quote: Decimal | None = None  # РјРёРЅРёРјР°Р»СЊРЅР°СЏ СЃСѓРјРјР° РІ РєРѕС‚РёСЂСѓРµРјРѕР№
    max_quote: Decimal | None = None  # Р°Р±СЃРѕР»СЋС‚РЅС‹Р№ РїРѕС‚РѕР»РѕРє РІ РєРѕС‚РёСЂСѓРµРјРѕР№


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
    Р–С‘СЃС‚РєРѕ Р·Р°РґР°РЅРЅР°СЏ СЃСѓРјРјР° (РЅР°РїСЂРёРјРµСЂ, FIXED_AMOUNT).
    РЈС‡РёС‚С‹РІР°РµРј РѕРіСЂР°РЅРёС‡РµРЅРёСЏ Рё (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ) max_quote_pct РѕС‚ РґРѕСЃС‚СѓРїРЅРѕРіРѕ free.
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
    Р”РѕР»СЏ РѕС‚ РґРѕСЃС‚СѓРїРЅРѕРіРѕ Р±Р°Р»Р°РЅСЃР° (РЅР°РїСЂРёРјРµСЂ, 5%).
    """
    f = dec(str(fraction or 0))
    v = free_quote_balance * f
    if constraints:
        # РїСЂРёРјРµРЅРёРј max_quote_pct, РµСЃР»Рё Р·Р°РґР°РЅ вЂ” Р±РµСЂС‘Рј РјРёРЅРёРјСѓРј РёР· РґРІСѓС… РѕРіСЂР°РЅРёС‡РёС‚РµР»РµР№
        if constraints.max_quote_pct and free_quote_balance:
            v = min(v, free_quote_balance * constraints.max_quote_pct)
        v = _clamp(v, min_v=constraints.min_quote, max_v=constraints.max_quote)
    return max(v, dec("0"))


def volatility_target_size(
    *,
    free_quote_balance: Decimal,
    market_vol_pct: Decimal,  # РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ СЂС‹РЅРєР° РІ РїСЂРѕС†РµРЅС‚Р°С… (РЅР°РїСЂРёРјРµСЂ, 1.2)
    target_portfolio_vol_pct: Decimal,  # С†РµР»РµРІР°СЏ РїРѕСЂС‚С„РµР»СЊРЅР°СЏ РІРѕР»Р° РІ РїСЂРѕС†РµРЅС‚Р°С… (РЅР°РїСЂРёРјРµСЂ, 0.5)
    base_fraction: Decimal,  # Р±Р°Р·РѕРІР°СЏ РґРѕР»СЏ, РЅР°РїСЂ. 0.05
    constraints: SizeConstraints | None,
) -> Decimal:
    """
    РџСЂРѕСЃС‚Р°СЏ СЃС…РµРјР° В«target volatilityВ»: С‡РµРј РІС‹С€Рµ РІРѕР»Р° СЂС‹РЅРєР° вЂ” С‚РµРј РјРµРЅСЊС€Рµ СЂР°Р·РјРµСЂ.
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
    РќР°РёРІРЅР°СЏ Kelly РїРѕ РѕР¶РёРґР°РЅРёСЋ (%): f* = win_rate/avg_loss - (1 - win_rate)/avg_win
    Р—РґРµСЃСЊ СЂР°Р±РѕС‚Р°РµРј РІ РґРѕР»СЏС… РЅР° СЃРґРµР»РєСѓ, РѕРіСЂР°РЅРёС‡РёРІР°РµРј cap (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ 50%).
    """
    if cap is None:
        cap = _DEFAULT_KELLY_CAP

    w = dec(str(win_rate or 0))
    aw = dec(str(avg_win_pct or 0)) / dec("100")
    al = dec(str(avg_loss_pct or 0)) / dec("100")
    if aw <= 0 or al <= 0:
        return dec("0")
    # РџСЂРѕСЃС‚РµР№С€Р°СЏ Р°РїРїСЂРѕРєСЃРёРјР°С†РёСЏ Kelly вЂ” РёСЃРїРѕР»СЊР·СѓР№С‚Рµ Р°РєРєСѓСЂР°С‚РЅРѕ
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
    РљРѕРЅРІРµСЂС‚РёСЂСѓРµРј Kelly-РґРѕР»СЋ РІ РєРѕС‚РёСЂСѓРµРјСѓСЋ СЃСѓРјРјСѓ СЃ РѕРіСЂР°РЅРёС‡РµРЅРёРµРј Р±Р°Р·РѕРІРѕР№ С„СЂР°РєС†РёРµР№.
    """
    k = naive_kelly(win_rate, avg_win_pct, avg_loss_pct)
    f = min(k, dec(str(base_fraction or 0)))
    v = free_quote_balance * f
    if constraints:
        if constraints.max_quote_pct and free_quote_balance:
            v = min(v, free_quote_balance * constraints.max_quote_pct)
        v = _clamp(v, min_v=constraints.min_quote, max_v=constraints.max_quote)
    return max(v, dec("0"))
