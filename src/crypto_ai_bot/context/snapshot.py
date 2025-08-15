# -*- coding: utf-8 -*-
"""
Р•РґРёРЅС‹Р№ В«СЃРЅРёРјРѕРє РєРѕРЅС‚РµРєСЃС‚Р°В» СЂС‹РЅРєР°: BTC Dominance, DXY (1d change), Fear & Greed.
РСЃС‚РѕС‡РЅРёРєРё Р·Р°РґР°СЋС‚СЃСЏ С‡РµСЂРµР· ENV (СЃ РґРµС„РѕР»С‚Р°РјРё РЅР° РЅР°С€Рё РјРѕРґСѓР»Рё market/*).
Р‘РµР·РѕРїР°СЃРЅС‹Рµ fallbacks: Р»СЋР±С‹Рµ РѕС€РёР±РєРё РЅРµ Р»РѕРјР°СЋС‚ С†РёРєР» вЂ” РїРѕР»СЏ РѕСЃС‚Р°СЋС‚СЃСЏ None/С„РѕР»Р±СЌРє.
"""

from __future__ import annotations

import os
import importlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from crypto_ai_bot.core.settings import Settings

logger = logging.getLogger(__name__)


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ helpers в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def _import_first_callable(module_path: str, candidates: tuple[str, ...]):
    """
    РџС‹С‚Р°РµС‚СЃСЏ РёРјРїРѕСЂС‚РёСЂРѕРІР°С‚СЊ РјРѕРґСѓР»СЊ module_path Рё РІРµСЂРЅСѓС‚СЊ РїРµСЂРІСѓСЋ РЅР°Р№РґРµРЅРЅСѓСЋ С„СѓРЅРєС†РёСЋ РёР· candidates.
    Р’РµСЂРЅС‘С‚ None, РµСЃР»Рё РЅРµ РїРѕР»СѓС‡РёР»РѕСЃСЊ.
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
    """Р’С‹Р·С‹РІР°РµС‚ С„СѓРЅРєС†РёСЋ Р±РµР·РѕРїР°СЃРЅРѕ: exceptions в†’ warning Рё None."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        name = getattr(fn, "__name__", fn.__class__.__name__)
        logger.warning(f"context source failed: {name}: {e}")
        return None


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ model в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@dataclass
class ContextSnapshot:
    market_condition: str = "SIDEWAYS"          # РіСЂСѓР±С‹Р№ СЂРµР¶РёРј (РёС‰РµС‚СЃСЏ РІ СЃРёРіРЅР°Р»Р°С… 4h/15m)
    btc_dominance: Optional[float] = None       # %
    dxy_change_1d: Optional[float] = None       # % РёР·РјРµРЅРµРЅРёРµ Р·Р° 1 РґРµРЅСЊ
    fear_greed: Optional[int] = None            # 0..100

    # РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ: РїРѕР»РµР·РЅС‹Рµ РјРµС‚Р°РґР°РЅРЅС‹Рµ
    meta: Dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def neutral() -> "ContextSnapshot":
        return ContextSnapshot()


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ public в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def build_context_snapshot(
    settings: Settings,
    exchange,      # ExchangeClient (РЅРµ РёСЃРїРѕР»СЊР·СѓРµРј Р·РґРµСЃСЊ, РЅРѕ РѕСЃС‚Р°РІР»СЏРµРј СЃРёРіРЅР°С‚СѓСЂСѓ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё)
    symbol: str,
    timeframe: str = "15m",
) -> ContextSnapshot:
    """
    РЎРѕР±РёСЂР°РµС‚ В«СЂРµР°Р»СЊРЅС‹Р№В» РєРѕРЅС‚РµРєСЃС‚: BTC.D, DXY(1d), Fear&Greed.
    РСЃС‚РѕС‡РЅРёРєРё Р±РµСЂСѓС‚СЃСЏ РёР· ENV:
      - BTC_DOMINANCE_SOURCE (default: crypto_ai_bot.context.market.btc_dominance)
            РѕР¶РёРґР°РµРј С„СѓРЅРєС†РёСЋ: fetch_btc_dominance() -> float|None
      - DXY_SOURCE (default: crypto_ai_bot.context.market.dxy_index)
            РѕР¶РёРґР°РµРј С„СѓРЅРєС†РёСЋ: dxy_change_pct_1d() -> float|None
      - FEAR_GREED_SOURCE (default: crypto_ai_bot.context.market.fear_greed)
            РѕР¶РёРґР°РµРј С„СѓРЅРєС†РёСЋ: fetch_fear_greed() -> int|None
    Р›СЋР±РѕР№ РёСЃС‚РѕС‡РЅРёРє РјРѕР¶РµС‚ РІРµСЂРЅСѓС‚СЊ None вЂ” СЌС‚Рѕ РѕРє.
    """
    timeout = int(os.getenv("CONTEXT_TIMEOUT_SEC", "6"))

    # 1) BTC Dominance (С‚РµРєСѓС‰РµРµ Р·РЅР°С‡РµРЅРёРµ, %)
    src_btc_dom = os.getenv("BTC_DOMINANCE_SOURCE", "crypto_ai_bot.context.market.btc_dominance")
    fn_btc = _import_first_callable(src_btc_dom, ("fetch_btc_dominance", "get_btc_dominance"))
    btc_dom = _safe_call(fn_btc, timeout=timeout) if fn_btc else None

    # 2) DXY: РґРЅРµРІРЅРѕРµ РёР·РјРµРЅРµРЅРёРµ РІ %
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

    # 4) РЎРѕР±РёСЂР°РµРј СЃРЅР°РїС€РѕС‚
    snap = ContextSnapshot(
        market_condition="SIDEWAYS",   # С„РёРЅР°Р»СЊРЅС‹Р№ СЂРµР¶РёРј С„РѕСЂРјРёСЂСѓРµС‚СЃСЏ РІ СЃРёРіРЅР°Р»-Р°РіСЂРµРіР°С‚РѕСЂРµ (4h/15m)
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





