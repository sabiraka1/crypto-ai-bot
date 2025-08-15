# -*- coding: utf-8 -*-
"""
РљРѕСЂСЂРµР»СЏС†РёСЏ СЃРёРјРІРѕР»Р° СЃ BTC.
Р‘РµР· РІРЅРµС€РЅРёС… API: СЃС‡РёС‚Р°РµРј РїРѕ С„Р°РєС‚РёС‡РµСЃРєРёРј СЃРІРµС‡Р°Рј С‡РµСЂРµР· ExchangeClient.get_ohlcv().
Р’РѕР·РІСЂР°С‰Р°РµРј РџРёСЂСЃРѕРЅ РєРѕСЂСЂРµР»СЏС†РёСЋ РґРѕС…РѕРґРЅРѕСЃС‚РµР№ (pct_change), СѓСЃРµС‡С‘РЅРЅСѓСЋ РґРѕ РїРѕСЃР»РµРґРЅРµРіРѕ РѕРєРЅР°.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
# Р’РЎРџРћРњРћР“РђРўР•Р›Р¬РќРћР•

def _ohlcv_to_series_close(ohlcv) -> pd.Series:
    """CCXT-СЃРѕРІРјРµСЃС‚РЅС‹Р№ OHLCV -> Series(close) СЃ РёРЅРґРµРєСЃРѕРј РїРѕ РІСЂРµРјРµРЅРё (UTC)."""
    if not ohlcv:
        return pd.Series(dtype=float)
    df = pd.DataFrame(
        ohlcv, columns=["time", "open", "high", "low", "close", "volume"]
    )
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    s = pd.to_numeric(df["close"], errors="coerce").dropna()
    return s

def _align_last_window(a: pd.Series, b: pd.Series, window: Optional[int]) -> Tuple[pd.Series, pd.Series]:
    """Р’С‹СЂР°РІРЅРёРІР°РµРј РїРѕ РѕР±С‰РµРјСѓ РёРЅРґРµРєСЃСѓ Рё РѕР±СЂРµР·Р°РµРј РЅР° РїРѕСЃР»РµРґРЅРёС… window С‚РѕС‡РµРє."""
    if a.empty or b.empty:
        return a, b
    joined = pd.concat([a, b], axis=1, join="inner").dropna()
    if joined.empty:
        return a.iloc[0:0], b.iloc[0:0]
    if window and len(joined) > window:
        joined = joined.iloc[-window:]
    a2 = joined.iloc[:, 0]
    b2 = joined.iloc[:, 1]
    return a2, b2

def _to_returns(s: pd.Series) -> pd.Series:
    """РџСЂРѕС†РµРЅС‚С‹ РёР·РјРµРЅРµРЅРёСЏ (РґРѕС…РѕРґРЅРѕСЃС‚Рё). РЈРґР°Р»СЏРµРј NaN/inf."""
    if s.empty:
        return s
    r = s.pct_change()
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    return r

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
# РћРЎРќРћР’РќР«Р• Р¤РЈРќРљР¦РР

def compute_correlation(a: pd.Series, b: pd.Series, window: Optional[int] = 96) -> Optional[float]:
    """
    РџРёСЂСЃРѕРЅ РєРѕСЂСЂРµР»СЏС†РёСЏ РґРѕС…РѕРґРЅРѕСЃС‚РµР№ РґР»СЏ РґРІСѓС… С†РµРЅРѕРІС‹С… СЂСЏРґРѕРІ.
    window: СЃРєРѕР»СЊРєРѕ РїРѕСЃР»РµРґРЅРёС… С‚РѕС‡РµРє Р±РµСЂС‘Рј (РЅР°РїСЂРёРјРµСЂ, 96 РґР»СЏ ~СЃСѓС‚РѕРє РЅР° 15m).
    """
    try:
        if a is None or b is None:
            return None
        a_ret = _to_returns(a)
        b_ret = _to_returns(b)
        a_al, b_al = _align_last_window(a_ret, b_ret, window)

        if len(a_al) < 10 or len(b_al) < 10:
            return None

        corr = float(np.corrcoef(a_al.values, b_al.values)[0, 1])
        # Р“Р°СЂР°РЅС‚РёСЂСѓРµРј РІ РґРёР°РїР°Р·РѕРЅРµ [-1, 1]
        return max(-1.0, min(1.0, corr))
    except Exception as e:
        logger.error(f"вќЊ compute_correlation failed: {e}", exc_info=True)
        return None


def compute_symbol_btc_corr(
    exchange,  # РѕР¶РёРґР°РµС‚СЃСЏ crypto_ai_bot.trading.exchange_client.ExchangeClient
    symbol: str,
    timeframe: str = "15m",
    limit: int = 200,
    btc_symbol: str = "BTC/USDT",
    window: int = 96,
) -> Optional[float]:
    """
    РЎС‡РёС‚Р°РµС‚ РєРѕСЂСЂРµР»СЏС†РёСЋ СЃРёРјРІРѕР»Р° СЃ BTC РїРѕ РґРѕС…РѕРґРЅРѕСЃС‚СЏРј.
    РСЃРїРѕР»СЊР·СѓРµС‚ exchange.get_ohlcv(). РќРёРєР°РєРёС… РІРЅРµС€РЅРёС… Р·Р°РїСЂРѕСЃРѕРІ.
    """
    try:
        # 1) РЎРІРµС‡Рё РїРѕ СЃРёРјРІРѕР»Сѓ
        ohlcv_sym = exchange.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
        close_sym = _ohlcv_to_series_close(ohlcv_sym)

        # 2) РЎРІРµС‡Рё РїРѕ BTC
        ohlcv_btc = exchange.get_ohlcv(btc_symbol, timeframe=timeframe, limit=limit)
        close_btc = _ohlcv_to_series_close(ohlcv_btc)

        # 3) РљРѕСЂСЂРµР»СЏС†РёСЏ
        corr = compute_correlation(close_sym, close_btc, window=window)
        logger.debug(
            f"рџ”— corr({symbol} ~ {btc_symbol}, tf={timeframe}, window={window}) -> {corr}"
        )
        return corr
    except Exception as e:
        logger.error(f"вќЊ compute_symbol_btc_corr failed: {e}", exc_info=True)
        return None


def classify_corr(value: Optional[float]) -> str:
    """
    Р“СЂСѓР±Р°СЏ РєР»Р°СЃСЃРёС„РёРєР°С†РёСЏ СЃРёР»С‹ СЃРІСЏР·Рё СЃ BTC.
    """
    if value is None:
        return "unknown"
    v = float(value)
    if v >= 0.75:
        return "strong_pos"
    if v >= 0.4:
        return "moderate_pos"
    if v > -0.4:
        return "weak"
    if v > -0.75:
        return "moderate_neg"
    return "strong_neg"


__all__ = [
    "compute_correlation",
    "compute_symbol_btc_corr",
    "classify_corr",
]










