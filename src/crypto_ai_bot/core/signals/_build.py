# src/crypto_ai_bot/core/signals/_build.py
from __future__ import annotations

from typing import Any, Dict, List

from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.indicators.unified import build_indicators


def build(cfg: Any, broker: ExchangeInterface, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Сбор фичей для решения. Минимальный контракт:
      {
        "ohlcv": [...],
        "indicators": {...},
        "context": {"btc_dominance": None, "fear_greed": None, "dxy": None}   # заполняется на уровне use-case (evaluate)
      }
    """
    # OHLCV
    ohlcv: List[List[float]] = broker.fetch_ohlcv(symbol, timeframe, limit)
    inds: Dict[str, Any] = build_indicators(ohlcv)

    return {
        "ohlcv": ohlcv,
        "indicators": inds,
        # под контекст — будет заполнено в evaluate(); здесь None, чтобы код не падал при обращении
        "context": {"btc_dominance": None, "fear_greed": None, "dxy": None},
        "meta": {"symbol": symbol, "timeframe": timeframe, "limit": int(limit)},
    }
