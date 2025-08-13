# -*- coding: utf-8 -*-
"""
Единый «снимок контекста» рынка: BTC Dominance, DXY (1d change), Fear & Greed.
Источники задаются через ENV (с дефолтами на наши модули market/*).
Безопасные fallbacks: любые ошибки не ломают цикл — поля остаются None/фолбэк.
"""

from __future__ import annotations

import os
import importlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from crypto_ai_bot.config.settings import Settings

logger = logging.getLogger(__name__)


# ─────────────────────────── helpers ───────────────────────────

def _import_first_callable(module_path: str, candidates: tuple[str, ...]):
    """
    Пытается импортировать модуль module_path и вернуть первую найденную функцию из candidates.
    Вернёт None, если не получилось.
    """
    try:
        mod = importlib.import_module(module_path)
        for name in candidates:
            fn = getattr(mod, name, None)
            if callable(fn):
                return fn
    except Exception as e:
        logger.debug(f"Context import failed for {module_path}: {e}")
    return None


def _safe_call(fn, *args, **kwargs):
    """Вызывает функцию безопасно: exceptions → warning и None."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        name = getattr(fn, "__name__", fn.__class__.__name__)
        logger.warning(f"context source failed: {name}: {e}")
        return None


# ─────────────────────────── model ───────────────────────────

@dataclass
class ContextSnapshot:
    market_condition: str = "SIDEWAYS"          # грубый режим (ищется в сигналах 4h/15m)
    btc_dominance: Optional[float] = None       # %
    dxy_change_1d: Optional[float] = None       # % изменение за 1 день
    fear_greed: Optional[int] = None            # 0..100

    # опционально: полезные метаданные
    meta: Dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def neutral() -> "ContextSnapshot":
        return ContextSnapshot()


# ─────────────────────────── public ───────────────────────────

def build_context_snapshot(
    settings: Settings,
    exchange,      # ExchangeClient (не используем здесь, но оставляем сигнатуру для совместимости)
    symbol: str,
    timeframe: str = "15m",
) -> ContextSnapshot:
    """
    Собирает «реальный» контекст: BTC.D, DXY(1d), Fear&Greed.
    Источники берутся из ENV:
      - BTC_DOMINANCE_SOURCE (default: crypto_ai_bot.context.market.btc_dominance)
            ожидаем функцию: fetch_btc_dominance() -> float|None
      - DXY_SOURCE (default: crypto_ai_bot.context.market.dxy_index)
            ожидаем функцию: dxy_change_pct_1d() -> float|None
      - FEAR_GREED_SOURCE (default: crypto_ai_bot.context.market.fear_greed)
            ожидаем функцию: fetch_fear_greed() -> int|None
    Любой источник может вернуть None — это ок.
    """
    timeout = int(os.getenv("CONTEXT_TIMEOUT_SEC", "6"))

    # 1) BTC Dominance (текущее значение, %)
    src_btc_dom = os.getenv("BTC_DOMINANCE_SOURCE", "crypto_ai_bot.context.market.btc_dominance")
    fn_btc = _import_first_callable(src_btc_dom, ("fetch_btc_dominance", "get_btc_dominance"))
    btc_dom = _safe_call(fn_btc, timeout=timeout) if fn_btc else None

    # 2) DXY: дневное изменение в %
    src_dxy = os.getenv("DXY_SOURCE", "crypto_ai_bot.context.market.dxy_index")
    fn_dxy = _import_first_callable(src_dxy, ("dxy_change_pct_1d", "get_dxy_change_pct_1d"))
    dxy_ch = _safe_call(fn_dxy, timeout=timeout) if fn_dxy else None

    # 3) Fear & Greed (0..100)
    src_fng = os.getenv("FEAR_GREED_SOURCE", "crypto_ai_bot.context.market.fear_greed")
    fn_fng = _import_first_callable(src_fng, ("fetch_fear_greed", "get_fng_value", "fear_greed_value"))
    fng_fb = int(os.getenv("FEAR_GREED_FALLBACK", "50"))
    fng = _safe_call(fn_fng, timeout=timeout) if fn_fng else None
    if fng is None:
        fng = fng_fb

    # 4) Собираем снапшот
    snap = ContextSnapshot(
        market_condition="SIDEWAYS",   # финальный режим формируется в сигнал-агрегаторе (4h/15m)
        btc_dominance=btc_dom,
        dxy_change_1d=dxy_ch,
        fear_greed=fng,
        meta={
            "source": "build_context_snapshot",
            "symbol": symbol,
            "timeframe": timeframe,
            "modules": {
                "btc_dom": src_btc_dom,
                "dxy": src_dxy,
                "fear_greed": src_fng,
            },
        },
    )
    snap.ts = datetime.now(timezone.utc)
    return snap


__all__ = ["ContextSnapshot", "build_context_snapshot"]
