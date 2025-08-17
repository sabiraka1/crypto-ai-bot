# src/crypto_ai_bot/market_context/snapshot.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.market_context import providers

def build_snapshot(cfg, http, breaker) -> Dict[str, Optional[float | str]]:
    """
    Собирает контекст рынка безопасно:
      - BTC dominance (проценты)
      - Fear & Greed (значение и текст)
      - DXY (если включён через CONTEXT_DXY_URL)
    Любая ошибка/таймаут → None, чтобы не портить основной флоу.
    """
    # если контекст выключен, возвращаем пустые поля
    if not getattr(cfg, "CONTEXT_ENABLE", True):
        return {
            "btc_dominance_percent": None,
            "fear_greed": None,
            "fear_greed_class": None,
            "dxy_index": None,
        }

    btc = providers.btc_dominance(cfg, http, breaker)
    fng_val, fng_class = providers.fear_greed(cfg, http, breaker)
    dxy = providers.dxy_index(cfg, http, breaker)

    return {
        "btc_dominance_percent": btc,
        "fear_greed": fng_val,
        "fear_greed_class": fng_class,
        "dxy_index": dxy,
    }
