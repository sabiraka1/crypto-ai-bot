from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Any, Dict

from crypto_ai_bot.utils.metrics import inc


class RateLimitExceeded(Exception):
    """Поднятие исключения при превышении лимита."""


class _FixedWindow:
    """
    Очень простой потокобезопасный лимитер по фиксированному окну (N вызовов / window_sec).
    Для продакшена этого достаточно; если понадобится — легко заменить на токен-бакет.
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


def _get_cfg(obj_or_kwargs: dict | Any) -> Any:
    """
    Вытаскивает cfg из аргументов целевой функции. Поддерживаем:
    - именованный параметр "cfg" (в kwargs)
    - первый позиционный аргумент, если у него есть атрибуты Settings
    """
    if isinstance(obj_or_kwargs, dict):
        if "cfg" in obj_or_kwargs:
            return obj_or_kwargs["cfg"]
        # иногда cfg передают как первый именованный параметр другого имени
        for v in obj_or_kwargs.values():
            if hasattr(v, "build") and hasattr(v, "__class__"):
                # не самый надёжный признак, но помогает
                return v
        return None
    return obj_or_kwargs


def guard_rate_limit(
    *,
    name: str,
    per_min: int | Callable[[Any], int],
    metric_prefix: str = "rl",
    key_fn: Optional[Callable[..., str]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Декоратор: ограничивает частоту вызовов функции.
    - name: базовое имя лимита ("evaluate", "place_order")
    - per_min: число вызовов в минуту (int) или функция от cfg → int
    - metric_prefix: префикс метрик (inc)
    - key_fn: функция построения ключа лимита (по умолчанию глобально на процесс и режим)
    Метрики:
      {metric_prefix}_calls_total
      {metric_prefix}_rate_limited_total
    """
    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            # Метрика "вызовов до лимита"
            inc(f"{metric_prefix}_calls_total")

            # Достаём cfg, пытаемся определить режим
            cfg = kwargs.get("cfg", None)
            if cfg is None and args:
                # иногда cfg передают первым аргументом
                # или же объект, где внутри есть ссылка на cfg — это не трогаем
                pass

            # лимит в минуту
            limit_val = per_min(cfg) if callable(per_min) else int(per_min)

            # ключ лимита
            mode = "paper"
            try:
                if getattr(cfg, "PAPER_MODE", True) is False:
                    mode = "live"
            except Exception:
                pass

            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                key = f"{name}:{mode}:global"

            if limit_val <= 0:
                # 0 — фактически «всё запрещено», считаем это как мгновенный rate_limit
                inc(f"{metric_prefix}_rate_limited_total", {"key": key})
                raise RateLimitExceeded(f"rate_limit_{name}: limit=0")

            if not _LIMITER.allow(key, limit=limit_val, window_sec=60):
                inc(f"{metric_prefix}_rate_limited_total", {"key": key})
                raise RateLimitExceeded(f"rate_limit_{name}: {limit_val}/min exceeded")

            return fn(*args, **kwargs)
        return _wrapped
    return _decorator
