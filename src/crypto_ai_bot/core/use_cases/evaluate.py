from __future__ import annotations
from typing import Any, Dict, Tuple

from crypto_ai_bot.core.signals._build import build as build_features
from crypto_ai_bot.core.signals._fusion import decide as decide_policy

async def evaluate(
    *,
    cfg: Any,
    broker: Any,
    positions_repo: Any | None,
    symbol: str,
    timeframe: str | None = None,
    external: dict | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Чистая оценка: строим фичи -> принимаем решение -> (decision, explain)
    """
    feat = await build_features(
        symbol,
        cfg=cfg,
        broker=broker,
        positions_repo=positions_repo,
        timeframe=timeframe,
        external=external,
    )
    decision, explain = decide_policy(symbol, feat, cfg=cfg)
    return decision, explain
