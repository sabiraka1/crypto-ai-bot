from __future__ import annotations
import time
from contextlib import contextmanager
from typing import Any

try:
    from prometheus_client import Counter, Histogram, Summary  # noqa: F401
except Exception:  # Библиотека может быть недоступна на dev-стендах
    Counter = Histogram = Summary = object  # type: ignore


def inc(metric: Any, value: float = 1.0) -> None:
    """Инкремент счётчика/гейджа; молча игнорирует неподходящие объекты."""
    try:
        metric.inc(value)  # type: ignore[attr-defined]
    except Exception:
        pass


def observe(metric: Any, value: float) -> None:
    """Наблюдение значения на Histogram/Summary; молча игнорирует ошибки."""
    try:
        metric.observe(value)  # type: ignore[attr-defined]
    except Exception:
        pass


@contextmanager
def timer(metric: Any):
    """Контекст-менеджер для измерения длительности и записи в метрику (секунды)."""
    start = time.time()
    try:
        yield
    finally:
        observe(metric, time.time() - start)