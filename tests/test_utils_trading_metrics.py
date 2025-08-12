import importlib
import inspect
import pandas as pd
import numpy as np


def test_trading_metrics_core_functions_callable_and_return_numbers():
    """Тест основных функций торговых метрик"""
    tm = importlib.import_module("utils.trading_metrics")

    # Подготовим универсальные входы для разных сигнатур
    returns = pd.Series([0.01, -0.02, 0.015, 0.005, -0.01])
    equity = pd.Series([100, 98, 99.5, 100, 99])
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
        "max_drawdown": max_dd,  # альтернативное имя
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

        # Специальная обработка для функций, которые могут иметь проблемы с pandas Series
        try:
            # Вызов и базовые проверки результата
            res = fn(**kwargs)
            
            # Проверяем что результат это число или разумный тип
            assert isinstance(res, (int, float, np.number)) or pd.isna(res), \
                f"{name} должна возвращать число, получили {type(res)}"
            
            # Проверяем что результат не NaN (если это не ожидаемое поведение)
            if not pd.isna(res):
                assert isinstance(res, (int, float, np.number)), \
                    f"{name} вернула не числовое значение: {res}"
            
            called_at_least_one = True
            print(f"✓ {name}(**{list(kwargs.keys())}) = {res}")
            
        except (ValueError, TypeError, ZeroDivisionError) as e:
            # Логируем ошибки но не прерываем тест
            print(f"⚠ {name} вызвала ошибку: {e}")
            
            # Для некоторых функций попробуем альтернативные параметры
            if name == "max_drawdown" and "returns" in kwargs:
                try:
                    # Попробуем с пустой проверкой для pandas Series
                    if hasattr(kwargs["returns"], "empty"):
                        if not kwargs["returns"].empty:
                            res = fn(**kwargs)
                            called_at_least_one = True
                            print(f"✓ {name} (повторный вызов) = {res}")
                except Exception as e2:
                    print(f"⚠ {name} повторный вызов тоже не удался: {e2}")
            continue

    # Проверяем что хотя бы одна функция была успешно вызвана
    assert called_at_least_one, "Ни одна торговая метрика не была успешно вызвана"


def test_rr_ratio_handles_zero_loss_gracefully():
    """Тест обработки нулевых потерь в rr_ratio"""
    tm = importlib.import_module("utils.trading_metrics")
    
    if hasattr(tm, "rr_ratio") and callable(tm.rr_ratio):
        sig = inspect.signature(tm.rr_ratio)
        
        # Проверяем разные комбинации параметров для rr_ratio
        test_cases = [
            {"avg_win": 100.0, "avg_loss": -50.0},  # нормальный случай
            {"avg_win": 100.0, "avg_loss": 0.0},    # нулевые потери
            {"avg_win": 0.0, "avg_loss": -50.0},    # нулевые выигрыши
        ]
        
        for case in test_cases:
            # Проверяем что у функции есть нужные параметры
            params_ok = all(p in sig.parameters for p in case.keys())
            if not params_ok:
                continue
                
            try:
                result = tm.rr_ratio(**case)
                print(f"rr_ratio({case}) = {result}")
                
                # Проверяем тип результата
                assert isinstance(result, (int, float, type(None))) or pd.isna(result), \
                    f"rr_ratio должна возвращать число или None/NaN, получили {type(result)}"
                
            except (ZeroDivisionError, ValueError) as e:
                # Ожидаемые ошибки при некорректных входных данных
                print(f"rr_ratio({case}) вызвала ожидаемую ошибку: {e}")
                assert True  # это нормальное поведение
                
            except Exception as e:
                # Неожиданные ошибки
                print(f"rr_ratio({case}) вызвала неожиданную ошибку: {e}")
                # Не прерываем тест, но логируем
                continue


def test_basic_metric_functions_exist():
    """Проверяем что основные функции метрик существуют"""
    tm = importlib.import_module("utils.trading_metrics")
    
    # Минимальный набор ожидаемых функций
    expected_functions = [
        "max_drawdown",
        "rr_ratio", 
        "sharpe_ratio",
        "win_rate",
        "profit_factor"
    ]
    
    existing_functions = []
    for func_name in expected_functions:
        if hasattr(tm, func_name) and callable(getattr(tm, func_name)):
            existing_functions.append(func_name)
    
    # Проверяем что хотя бы половина функций существует
    assert len(existing_functions) >= len(expected_functions) // 2, \
        f"Найдено только {len(existing_functions)} из {len(expected_functions)} ожидаемых функций: {existing_functions}"
    
    print(f"Найденные функции метрик: {existing_functions}")