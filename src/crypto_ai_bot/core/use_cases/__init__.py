# src/crypto_ai_bot/core/use_cases/__init__.py
from __future__ import annotations

"""
Ленивые прокси для публичных use-cases.
Исключает циклические импорты при загрузке пакета.
"""

__all__ = ["evaluate", "place_order", "eval_and_execute"]


def evaluate(*args, **kwargs):
    from .evaluate import evaluate as _evaluate
    return _evaluate(*args, **kwargs)


def place_order(*args, **kwargs):
    from .place_order import place_order as _place_order
    return _place_order(*args, **kwargs)


def eval_and_execute(*args, **kwargs):
    from .eval_and_execute import eval_and_execute as _eval_and_execute
    return _eval_and_execute(*args, **kwargs)
