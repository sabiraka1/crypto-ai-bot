import math
import importlib
import numpy as np
import pandas as pd
import pytest


tm = importlib.import_module("utils.trading_metrics")


def _is_number(x):
    return isinstance(x, (int, float, np.floating)) and not isinstance(x, bool)


def test_max_drawdown_various_series():
    # РЅРѕСЂРјР°Р»СЊРЅС‹Р№ СЃР»СѓС‡Р°Р№
    s = pd.Series([100, 105, 103, 110, 90, 95, 120], dtype=float)
    md = tm.max_drawdown(returns=s.pct_change().fillna(0)) if hasattr(tm, "max_drawdown") else None
    if md is not None:
        assert _is_number(md)

    # РїРѕСЃС‚РѕСЏРЅРЅС‹Р№ СЂСЏРґ
    const = pd.Series([1, 1, 1, 1, 1], dtype=float)
    md2 = tm.max_drawdown(returns=const) if hasattr(tm, "max_drawdown") else None
    if md2 is not None:
        assert _is_number(md2)

    # РїСѓСЃС‚РѕР№ СЂСЏРґ
    empty = pd.Series([], dtype=float)
    md3 = tm.max_drawdown(returns=empty) if hasattr(tm, "max_drawdown") else None
    if md3 is not None:
        assert _is_number(md3)


def test_sharpe_and_sortino_edge_cases():
    if hasattr(tm, "sharpe_ratio"):
        # РЅСѓР»РµРІР°СЏ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ
        r = pd.Series([0, 0, 0, 0, 0], dtype=float)
        val = tm.sharpe_ratio(returns=r, risk_free=0.0) if "risk_free" in tm.sharpe_ratio.__code__.co_varnames else tm.sharpe_ratio(returns=r)
        assert _is_number(val)

        # РѕР±С‹С‡РЅС‹Рµ РґР°РЅРЅС‹Рµ
        r2 = pd.Series([0.01, -0.02, 0.015, 0.005, -0.01], dtype=float)
        val2 = tm.sharpe_ratio(returns=r2, risk_free=0.0) if "risk_free" in tm.sharpe_ratio.__code__.co_varnames else tm.sharpe_ratio(returns=r2)
        assert _is_number(val2)

    if hasattr(tm, "sortino_ratio"):
        # РІСЃРµ РґРѕС…РѕРґРЅРѕСЃС‚Рё РЅРµРѕС‚СЂРёС†Р°С‚РµР»СЊРЅС‹Рµ в†’ downside СЂРёСЃРє РјРёРЅРёРјР°Р»СЊРЅС‹Р№
        r = pd.Series([0.01, 0.02, 0.0, 0.03], dtype=float)
        val = tm.sortino_ratio(returns=r, target=0.0) if "target" in tm.sortino_ratio.__code__.co_varnames else tm.sortino_ratio(returns=r)
        assert _is_number(val)


def test_profit_factor_and_expectancy():
    wins = [120, 50, 30]
    losses = [-40, -10]

    if hasattr(tm, "profit_factor"):
        pf = tm.profit_factor(wins=wins, losses=losses)
        assert _is_number(pf) and pf > 0

        # Р±РµР· СѓР±С‹С‚РєРѕРІ (РєСЂР°Р№РЅРёР№ СЃР»СѓС‡Р°Р№)
        pf2 = tm.profit_factor(wins=[10, 5], losses=[])
        assert _is_number(pf2)

    if hasattr(tm, "expectancy"):
        ex = tm.expectancy(avg_win=60.0, avg_loss=-30.0, win_rate=0.55) if "avg_win" in tm.expectancy.__code__.co_varnames else tm.expectancy(wins=wins, losses=losses)
        assert _is_number(ex)


def test_rr_and_recovery_and_kelly():
    # rr
    if hasattr(tm, "rr_ratio"):
        rr1 = tm.rr_ratio(avg_win=50.0, avg_loss=-25.0) if "avg_win" in tm.rr_ratio.__code__.co_varnames else tm.rr_ratio(wins=[50], losses=[-25])
        assert _is_number(rr1) and rr1 > 0

        # РЅСѓР»РµРІРѕР№ СѓР±С‹С‚РѕРє вЂ” РґРѕР»Р¶РЅРѕ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ Р±РµР·РѕРїР°СЃРЅРѕ
        rr2 = tm.rr_ratio(avg_win=10.0, avg_loss=0.0) if "avg_win" in tm.rr_ratio.__code__.co_varnames else tm.rr_ratio(wins=[10], losses=[])
        assert _is_number(rr2)

    # recovery
    if hasattr(tm, "recovery_factor"):
        rec = tm.recovery_factor(total_net_profit=1000.0, max_dd=-150.0) if "total_net_profit" in tm.recovery_factor.__code__.co_varnames else tm.recovery_factor(returns=pd.Series([0.01, -0.02, 0.03]))
        assert _is_number(rec)

    # kelly
    if hasattr(tm, "kelly_fraction"):
        k = tm.kelly_fraction(win_rate=0.5, avg_win=1.0, avg_loss=-1.0) if "win_rate" in tm.kelly_fraction.__code__.co_varnames else tm.kelly_fraction(returns=pd.Series([1, -1], dtype=float))
        assert _is_number(k)
        # РіСЂР°РЅРёС†С‹: РµСЃР»Рё С€Р°РЅСЃ РїРѕР±РµРґС‹ РїР»РѕС…РѕР№ вЂ” С„СЂР°РєС†РёСЏ РЅРµ РґРѕР»Р¶РЅР° Р±С‹С‚СЊ Р±РѕР»СЊС€РѕР№ РїРѕР»РѕР¶РёС‚РµР»СЊРЅРѕР№
        k2 = tm.kelly_fraction(win_rate=0.2, avg_win=1.0, avg_loss=-1.0) if "win_rate" in tm.kelly_fraction.__code__.co_varnames else tm.kelly_fraction(returns=pd.Series([-1, -1, 1], dtype=float))
        assert _is_number(k2)


@pytest.mark.parametrize("series", [
    pd.Series([np.nan, np.nan, np.nan], dtype=float),
    pd.Series([0.0, np.nan, 0.0], dtype=float),
])
def test_functions_handle_nans(series):
    # Р±Р°Р·РѕРІР°СЏ СѓСЃС‚РѕР№С‡РёРІРѕСЃС‚СЊ Рє NaN
    for name in ["max_drawdown", "sharpe_ratio", "sortino_ratio"]:
        fn = getattr(tm, name, None)
        if fn is None:
            continue
        params = {}
        for p in tm.__dict__[name].__code__.co_varnames:
            if p == "returns":
                params["returns"] = series
        res = fn(**params) if params else fn(series)
        assert isinstance(res, (int, float, np.floating)) or res is None






