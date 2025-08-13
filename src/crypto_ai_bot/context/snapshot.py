# -*- coding: utf-8 -*-
"""
Единый «снимок контекста» рынка для скоринга/бота.
Никаких внешних HTTP-запросов здесь — только вызовы модулей из context.market.*
и внутренних сервисов (например, ExchangeClient) + безопасные fallbacks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from crypto_ai_bot.config.settings import Settings

# Модули контекста. Импортируем бережно: если чего-то нет — не падаем.
try:
    from .market.correlation import compute_symbol_btc_corr, classify_corr
except Exception:  # pragma: no cover
    compute_symbol_btc_corr = None  # type: ignore
    classify_corr = lambda _v: "unknown"  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class ContextSnapshot:
    """
    Минимальный пригодный контекст.
    Все поля Optional: если источник временно недоступен — просто None.
    """
    market_condition: str = "SIDEWAYS"        # грубая оценка режима
    atr_pct: Optional[float] = None           # % ATR от цены (если где-то посчитали)
    btc_dominance_delta: Optional[float] = None   # ∆ BTC.D (например, 24h), в процентах
    dxy_delta: Optional[float] = None             # ∆ DXY (например, 5d), в процентах
    fear_greed: Optional[int] = None              # индекс «страх/жадность» (0..100)
    corr_btc_15m: Optional[float] = None         # корреляция с BTC по 15m
    corr_class: str = "unknown"                   # классификация корреляции
    meta: Dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Удобный фабричный метод
    @staticmethod
    def neutral() -> "ContextSnapshot":
        return ContextSnapshot()

# ──────────────────────────────────────────────────────────────────────────────

def _safe_call(fn, *args, **kwargs):
    """Вызывает функцию безопасно: ошибки → лог, результат → None."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"context source failed: {getattr(fn, '__name__', fn)}: {e}")
        return None


def build_context_snapshot(
    settings: Settings,
    exchange,      # ExchangeClient
    symbol: str,   # например "BTC/USDT"
    timeframe: str = "15m",
) -> ContextSnapshot:
    """
    Сбор «реального» контекста с безопасными отказами.
    BTC.D / DXY / Fear&Greed берём из модулей context.market.*, если они есть.
    Корреляцию считаем локально через свечи (без HTTP).
    """

    snap = ContextSnapshot.neutral()

    # 1) BTC Dominance (если модуль подключён)
    try:
        from .market import btc_dominance as _bd  # type: ignore
        # Пробуем популярные имена функций
        fn = (
            getattr(_bd, "get_btc_dominance_delta", None)
            or getattr(_bd, "fetch_btc_dominance_delta", None)
            or getattr(_bd, "btc_dominance_delta", None)
        )
        if callable(fn):
            snap.btc_dominance_delta = _safe_call(fn)
    except Exception:
        pass

    # 2) DXY (если модуль подключён)
    try:
        from .market import dxy_index as _dxy  # type: ignore
        fn = (
            getattr(_dxy, "get_dxy_delta", None)
            or getattr(_dxy, "fetch_dxy_delta", None)
            or getattr(_dxy, "dxy_delta", None)
        )
        if callable(fn):
            snap.dxy_delta = _safe_call(fn)
    except Exception:
        pass

    # 3) Fear & Greed (если модуль подключён)
    try:
        from .market import fear_greed as _fg  # type: ignore
        fn = (
            getattr(_fg, "get_fng_value", None)
            or getattr(_fg, "fetch_fng_value", None)
            or getattr(_fg, "fear_greed_value", None)
        )
        if callable(fn):
            snap.fear_greed = _safe_call(fn)
    except Exception:
        pass

    # 4) Корреляция символа с BTC — считаем из свечей через ExchangeClient
    if callable(compute_symbol_btc_corr):
        snap.corr_btc_15m = _safe_call(
            compute_symbol_btc_corr,
            exchange,
            symbol,
            timeframe=timeframe,
            limit=getattr(settings, "OHLCV_LIMIT", 200),
            btc_symbol="BTC/USDT",
            window=96,  # ~сутки на 15m
        )
        snap.corr_class = classify_corr(snap.corr_btc_15m)

    # 5) Простая эвристика режима рынка
    #    Можно заменить на более продвинутый детектор, когда он будет готов.
    cond = "SIDEWAYS"
    try:
        bd = snap.btc_dominance_delta
        dx = snap.dxy_delta
        if bd is not None and dx is not None:
            if bd < 0 and dx < 0:
                cond = "BULLISH"
            elif bd > 0 and dx > 0:
                cond = "BEARISH"
        # небольшая поправка по сильной корреляции с BTC
        if snap.corr_btc_15m is not None and snap.corr_btc_15m >= 0.75:
            cond = "RISK_ON"
    except Exception:
        pass

    snap.market_condition = cond
    snap.meta.update({
        "source": "build_context_snapshot",
        "timeframe": timeframe,
        "symbol": symbol,
    })
    snap.ts = datetime.now(timezone.utc)
    return snap


__all__ = ["ContextSnapshot", "build_context_snapshot"]
