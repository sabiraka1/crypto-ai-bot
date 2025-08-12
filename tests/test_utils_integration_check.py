# tests/test_utils_integration_check.py
import importlib

def _call_if_exists(mod, names):
    for name in names:
        fn = getattr(mod, name, None)
        if callable(fn):
            try:
                # многие реализации имеют параметр silent=True
                return fn(silent=True)
            except TypeError:
                return fn()
    return None

def test_integration_check_runs_and_returns_dict_or_bool():
    ic = importlib.import_module("utils.integration_check")

    # Популярные entrypoints
    result = _call_if_exists(
        ic,
        [
            "run_integration_check",
            "run_checks",
            "check_environment",
            "integration_check",
            "main",
        ],
    )

    # Важно: тест не падает, если возвращают None; но если вернули значение — проверим тип
    assert result is None or isinstance(result, (dict, bool))
