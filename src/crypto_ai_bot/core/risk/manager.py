from __future__ import annotations

from typing import Tuple, Callable, Any

from . import rules  # noqa: F401


def _call_rule(fn: Callable[..., Tuple[bool, str]], features: dict, cfg) -> Tuple[bool, str]:
    """
    Поддерживаем разные сигнатуры правил:
      - rule(features, cfg)
      - rule(features)
      - rule(cfg)
    """
    try:
        return fn(features, cfg)        # type: ignore[misc]
    except TypeError:
        try:
            return fn(features)         # type: ignore[misc]
        except TypeError:
            return fn(cfg)              # type: ignore[misc]


def check(features: dict, cfg) -> Tuple[bool, str]:
    """
    Агрегатор правил → первый FAIL останавливает конвейер.
    Порядок важен: time_sync сначала, чтобы быстро отрубать торговлю.
    """
    order = [
        "check_time_sync",       # новый критичный стоп
        "check_spread",
        "check_hours",
        "check_dd",
        "check_seq_losses",
        "check_max_exposure",
    ]

    for name in order:
        if hasattr(rules, name):
            ok, reason = _call_rule(getattr(rules, name), features, cfg)
            if not ok:
                return False, reason or name

    return True, ""
