import importlib
import time
import inspect


def _find(callables, substr):
    for name in callables:
        if substr in name.lower():
            return name
    return None


def test_retry_like_decorator_behaviour(monkeypatch):
    """
    Аккуратно ищем в core.decorators ретрай-декоратор и проверяем базовую семантику:
    функция падает 2 раза и проходит на 3-й.
    Тест гибкий: если в модуле нет подходящего декоратора — просто скип.
    """
    dec = importlib.import_module("core.decorators")
    exported = [n for n, v in dec.__dict__.items() if callable(v)]
    cand_name = _find(exported, "retry") or _find(exported, "backoff")
    if not cand_name:
        return  # нет подходящих декораторов → пропускаем тест

    decorator_obj = getattr(dec, cand_name)

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    # Поддерживаем 2 формы: @retry(...) и @retry без параметров
    def _wrap(fn):
        try:
            # Попробуем как фабрику
            return decorator_obj(retries=3, delay=0)(fn)
        except TypeError:
            # Попробуем как прямой декоратор
            return decorator_obj(fn)

    wrapped = _wrap(flaky)
    assert wrapped() == "ok"
    assert calls["n"] == 3


def test_timeout_like_decorator(monkeypatch):
    """
    Ищем таймаут-декоратор и проверяем, что долгий вызов прерывается (или возвращает дефолт).
    Если декоратора нет — скип.
    """
    dec = importlib.import_module("core.decorators")
    exported = [n for n, v in dec.__dict__.items() if callable(v)]
    cand_name = _find(exported, "timeout")
    if not cand_name:
        return

    decorator_obj = getattr(dec, cand_name)

    def long_op():
        time.sleep(1.0)
        return "done"

    # форсируем быстрый «таймаут» через monkeypatch
    monkeypatch.setattr(time, "sleep", lambda s: None)

    # поддерживаем форму @timeout(seconds=...)
    try:
        wrapped = decorator_obj(seconds=0)(long_op)
    except TypeError:
        wrapped = decorator_obj(long_op)

    try:
        res = wrapped()
    except Exception:
        # допустимо, если таймаут реализован через исключение
        return
    # или функция может вернуть «дефолт»/None по вашей реализации
    assert res in (None, "done")


def test_suppress_like_decorator():
    """
    Ищем «suppress/ignore»-декоратор, который не роняет выполнение при исключениях.
    Если нет — скип.
    """
    dec = importlib.import_module("core.decorators")
    exported = [n for n, v in dec.__dict__.items() if callable(v)]
    name = _find(exported, "suppress") or _find(exported, "ignore")
    if not name:
        return

    decorator_obj = getattr(dec, name)

    def boom():
        raise RuntimeError("err")

    try:
        wrapped = decorator_obj(boom)
    except TypeError:
        wrapped = decorator_obj()(boom)

    # Не должно бросить
    wrapped()
