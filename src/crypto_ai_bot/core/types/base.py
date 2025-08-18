# src/crypto_ai_bot/core/types/base.py
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, TypedDict, NotRequired


class StrAnyDict(TypedDict, total=False):
    # Универсальный dict[str, Any] для типизации мест, где структура динамическая
    # (облегчает mypy/pyright, не влияет на рантайм)
    __any__: Any


Json = Any  # упрощённый алиас
Labels = Mapping[str, str]
MutableLabels = MutableMapping[str, str]


class ResultOk(TypedDict):
    status: str  # "ok"
    detail: NotRequired[str]


class ResultErr(TypedDict):
    status: str  # "error"
    error: str
