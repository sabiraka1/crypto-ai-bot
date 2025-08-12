# tests/test_utils_trading_metrics.py
import importlib
import inspect
import math

import numpy as np
import pandas as pd

def _is_number(x):
    return isinstance(x, (int, float, np.floating)) and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))

def test_trading_metrics_core_functions_callable_and_return_numbers():
    tm = importlib.import_module("utils.trading_metrics")

    # Подготовим универсальные входы для разных сигнатур
    returns = pd.Series([0.01, -0.02, 0.015, 0.005, -0.01])
    equity  = pd.Series([100, 98, 99.5, 100, 99])
    wins, losses = [120, 50, 30], [-40, -10]
    avg_win, avg_loss, win_rate = 60.0, -30.0, 0.55
    total_net_profit, max_dd = 1000.0, -150.0

    # Карта «узнаваемых» параметров → готовые значения
    param_pool = {
        "returns": returns,
        "equity": equity,
        "wins": wins,
        "losses": losses,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_rate": win_rate,
        "total_net_profit": total_net_profit,
        "max_dd": max_dd,
    }

    # Функции, которые обычно присутствуют в модуле метрик
    candidates = [
        "win_rate",
        "profit_factor",
        "expectancy",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown",
        "rr_ratio",
        "recovery_factor",
        "kelly_fraction",
    ]

    called_at_least_one = False

    for name in candidates:
        fn = getattr(tm, name, None)
        if fn is None or not callable(fn):
            continue

        sig = inspect.signature(fn)
        kwargs = {}

        # Попробуем собрать kwargs из доступных ключей
        ok = True
        for p in sig.parameters.values():
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            if p.name in param_pool:
                kwargs[p.name] = param_pool[p.name]
            elif p.default is inspect._empty:
                ok = False
                break  # обязательный параметр, которого у нас нет

        if not ok:
            continue

        # Вызов и базовые проверки результата
        res = fn(**kwargs)
        # Разрешим любые численные скаляры; если возвращается кортеж — проверим, что там числа
        if isinstance(res, tuple):
            assert all(_is_number(x) for x in res if x is not None)
        else:
            assert _is_number(res) or res is None

        called_at_least_one = True

    assert called_at_least_one, "Не удалось вызвать ни одну метрику — проверьте имена функций в utils/trading_metrics.py"


def test_rr_ratio_handles_zero_loss_gracefully():
    # Проверяем частный случай: если в реализации rr_ratio деление на ноль — ждём inf
    tm = importlib.import_module("utils.trading_metrics")
    if hasattr(tm, "rr_ratio"):
        val = tm.rr_ratio(avg_win=10.0, avg_loss=0.0)  # ожидаемое поведение: inf
        assert val == np.inf
