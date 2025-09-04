from __future__ import annotations

import os
import time
from contextlib import contextmanager, asynccontextmanager
from typing import Any, AsyncIterator, Iterator

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
except Exception as _imp_err:  # noqa: BLE001
    # мягкий no-op фолбэк, если prometheus_client не установлен
    CollectorRegistry = object  # type: ignore[assignment]
    Counter = Gauge = Histogram = object  # type: ignore[assignment]

    def generate_latest(_r: Any) -> bytes:  # type: ignore[no-redef]
        return b""


_REGISTRY = CollectorRegistry() if isinstance(CollectorRegistry, type) else CollectorRegistry  # type: ignore[call-arg]
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}
_GAUGES: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}
_HISTS: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}

# глобальный флаг: можно отключить метрики полностью (например, в юнит-тестах)
_DISABLED = os.environ.get("METRICS_DISABLED", "0") == "1"


def reset_registry() -> None:
    """Сброс реестра для тестов."""
    global _REGISTRY, _COUNTERS, _GAUGES, _HISTS
    if _DISABLED:
        _COUNTERS = {}
        _GAUGES = {}
        _HISTS = {}
        return
    _REGISTRY = CollectorRegistry() if isinstance(CollectorRegistry, type) else CollectorRegistry  # type: ignore[call-arg]
    _COUNTERS = {}
    _GAUGES = {}
    _HISTS = {}


def _sanitize_name(name: str) -> str:
    """Prometheus-совместимость: точки/дефисы -> подчёркивания."""
    return name.replace(".", "_").replace("-", "_")


def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    pairs = tuple(sorted((labels or {}).items()))
    return (name, pairs)


def _buckets_ms() -> tuple[float, ...]:
    env = os.environ.get("METRICS_BUCKETS_MS", "5,10,25,50,100,250,500,1000")
    try:
        vals = [float(x.strip()) for x in env.split(",") if x.strip()]
    except Exception:
        vals = [5, 10, 25, 50, 100, 250, 500, 1000]
    # prometheus принимает секунды
    return tuple(v / 1000.0 for v in vals)


def _ensure_counter(name: str, labs: dict[str, str]) -> Any:
    if _DISABLED or Counter is object:
        return None
    k = _key(name, labs)
    if k not in _COUNTERS:
        try:
            _COUNTERS[k] = Counter(name, name, list(labs.keys()), registry=_REGISTRY)  # type: ignore[call-arg]
        except Exception:
            # несовместимые лейблы для уже зарегистрированной метрики — пропускаем
            return None
    return _COUNTERS[k].labels(**labs)  # type: ignore[no-any-return]


def _ensure_gauge(name: str, labs: dict[str, str]) -> Any:
    if _DISABLED or Gauge is object:
        return None
    k = _key(name, labs)
    if k not in _GAUGES:
        try:
            _GAUGES[k] = Gauge(name, name, list(labs.keys()), registry=_REGISTRY)  # type: ignore[call-arg]
        except Exception:
            return None
    return _GAUGES[k].labels(**labs)  # type: ignore[no-any-return]


def _ensure_hist(name: str, labs: dict[str, str]) -> Any:
    if _DISABLED or Histogram is object:
        return None
    k = _key(name, labs)
    if k not in _HISTS:
        try:
            _HISTS[k] = Histogram(  # type: ignore[call-arg]
                name, name, list(labs.keys()), buckets=_buckets_ms(), registry=_REGISTRY
            )
        except Exception:
            return None
    return _HISTS[k].labels(**labs)  # type: ignore[no-any-return]


# -------------------- ПУБЛИЧНОЕ API --------------------


def inc(name: str, **labels: Any) -> None:
    """Counter +1"""
    if _DISABLED:
        return
    name = _sanitize_name(name)
    labs = {k: str(v) for k, v in labels.items()}
    c = _ensure_counter(name, labs)
    if c is not None:
        c.inc()


def gauge(name: str, **labels: Any):
    """Gauge (вернёт объект, чтобы .set())"""
    if _DISABLED:
        return None
    name = _sanitize_name(name)
    labs = {k: str(v) for k, v in labels.items()}
    return _ensure_gauge(name, labs)


def hist(name: str, **labels: Any):
    """Histogram (секунды)"""
    if _DISABLED:
        return None
    name = _sanitize_name(name)
    labs = {k: str(v) for k, v in labels.items()}
    return _ensure_hist(name, labs)


def observe(name: str, value_ms: float, labels: dict[str, Any] | None = None) -> None:
    """Шорткат для наблюдения значения (миллисекунды -> секунды)."""
    if _DISABLED:
        return
    name = _sanitize_name(name)
    h = _ensure_hist(name, {k: str(v) for k, v in (labels or {}).items()})
    if h:
        h.observe(float(value_ms) / 1000.0)


def export_text() -> str:
    """Для /metrics в FastAPI."""
    if _DISABLED:
        return ""
    try:
        return generate_latest(_REGISTRY).decode("utf-8")  # type: ignore[arg-type]
    except Exception:
        return ""


# -------- таймеры (удобно мерить латентность блоков кода) --------


@contextmanager
def timer(name: str, **labels: Any) -> Iterator[None]:
    """
    Синхронный контекст-менеджер:
        with timer("orders.create.ms", exchange="gate"):
            do_work()
    """
    if _DISABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        observe(name, dt_ms, labels)


@asynccontextmanager
async def atimer(name: str, **labels: Any) -> AsyncIterator[None]:
    """
    Асинхронный контекст-менеджер:
        async with atimer("broker.request.ms", fn="fetch_balance"):
            await broker.fetch_balance(...)
    """
    if _DISABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        observe(name, dt_ms, labels)
