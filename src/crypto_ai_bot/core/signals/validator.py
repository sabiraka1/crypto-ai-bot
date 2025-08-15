from __future__ import annotations
from typing import Dict, Any
import math

def validate_features(features: Dict[str, Any], *_args, **_kwargs) -> Dict[str, float]:
    """
    Оставляем только числовые finite-значения.
    Сигнатура гибкая для обратной совместимости.
    """
    out: Dict[str, float] = {}
    for k, v in features.items():
        try:
            fv = float(v)
            if math.isfinite(fv):
                out[k] = fv
        except Exception:
            continue
    return out

# Back-compat: в некоторых местах проект ожидает validate(...)
validate = validate_features

__all__ = ["validate_features", "validate"]
