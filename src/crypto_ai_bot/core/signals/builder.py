from __future__ import annotations
from typing import Any, Dict, Tuple

# Единая точка сборки сигналов: вся агрегация — в _fusion
from ._fusion import fuse_signals, Explain


def build_signal(context: Dict[str, Any], indicators: Dict[str, float]) -> Tuple[float, Explain]:
    """
    Сконструировать итоговый скор ([-1..+1]) и объяснение по входящим индикаторам.
    Контракт совместим с прежними вызовами builder.build_signal(...).
    """
    score, explain = fuse_signals(indicators=indicators, ctx=context)
    return score, explain
