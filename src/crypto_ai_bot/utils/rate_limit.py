# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Any, Dict

from crypto_ai_bot.utils.metrics import inc


class RateLimitExceeded(Exception):
    """Поднятие исключения при превышении лимита."""


class _FixedWindow:
    """
    Потокобезопасный лимитер по фиксированному окну (N вызовов / window_sec).
    Для продакшена достаточно; легко заменить на токен-бакет при необходимости.
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> {"start": epoch_sec, "count": int}
        self._state: Dict[str, Dict[str, float]] = {}

    def allow(self, key: str, limit: int, window_sec: int = 60) -> bool:
        now = int(time.time())
        with self._lock:
            st = self._state.get(key)
            if not st or now - int(st["start"]) >= window_sec:
                # новое окно
                self._state[key] = {"start": float(now), "count": 1.0}
                return True
            # то же окно
            if st["count"] < float(limit):
                st["count"] += 1.0
                return True
            return False


# Глобальный реестр лимитов (в процессе)
_LIMITER = _FixedWindow()


def _detect_mode(cfg: Any) -> str:
    try:
        # В проекте есть Settings.MODE, но на всякий случай мягко определим
        mode = getattr(cfg, "MODE", None)
        if mode:
            return str(mode)
    except Exception:
        pass
    return "paper"


def guard_rate_limit(
    *,
    name: str,
    per_min: int | Callable[[Any], int],
    metric_prefix: str = "rl",
    key_fn: Optional[Callable[..., str]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Декоратор: ограничивает частоту вызовов функции.
    Метрики:
      {metric_prefix}_calls_total
      {metric_prefix}_rate_limited_total
    """
    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            # Метрика "вызовов до лимита"
            inc(f"{metric_prefix}_calls_total")

            # cfg может приходить либо первым позиционным (UC), либо именованным
            cfg = kwargs.get("cfg", None)
            if cfg is None and args:
                cfg = args[0]  # UC обычно первым аргументом передают cfg

            # лимит в минуту
            limit_val = per_min(cfg) if callable(per_min) else int(per_min)

            # ключ лимита
            mode = _detect_mode(cfg)
            key = key_fn(*args, **kwargs) if key_fn else f"{name}:{mode}:global"

            if limit_val <= 0:
                inc(f"{metric_prefix}_rate_limited_total", {"key": key})
                raise RateLimitExceeded(f"rate_limit_{name}: limit=0")

            if not _LIMITER.allow(key, limit=limit_val, window_sec=60):
                inc(f"{metric_prefix}_rate_limited_total", {"key": key})
                raise RateLimitExceeded(f"rate_limit_{name}: {limit_val}/min exceeded")

            return fn(*args, **kwargs)
        return _wrapped
    return _decorator


def rate_limit(*, limit: int, per: int = 60, name: Optional[str] = None, metric_prefix: str = "rl"):
    """
    Совместимая с UC обёртка:
    @rate_limit(limit=60, per=60) → фикс-окно 60/мин.
    """
    # name берём из функции, если не задан
    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        nm = name or getattr(fn, "__name__", "fn")
        # per всегда 60 для "per minute"; limit — фактический лимит
        return guard_rate_limit(name=nm, per_min=limit, metric_prefix=metric_prefix)(_wrap_name(fn, nm))
    return _decorator


def _wrap_name(fn: Callable[..., Any], name: str) -> Callable[..., Any]:
    fn.__name__ = name  # полезно для метрик/логов
    return fn
