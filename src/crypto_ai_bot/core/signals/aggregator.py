
# -*- coding: utf-8 -*-
"""
crypto_ai_bot.core.signals.aggregator
------------------------------------
Р РѕР±Р°СЃС‚РЅС‹Р№ Р°РіСЂРµРіР°С‚РѕСЂ С„РёС‡ (Phase 3):
- 3 СЂРµС‚СЂР°СЏ fetch_ohlcv;
- fallback РЅР° fetch_ticker (РјРёРЅРёРјР°Р»СЊРЅС‹Р№
  РЅР°Р±РѕСЂ РїСЂРёР·РЅР°РєРѕРІ, РЅРѕ РќРРљРћР“Р”Рђ РЅРµ РєРёРґР°РµС‚ РёСЃРєР»СЋС‡РµРЅРёРµ);
- РІСЃРµРіРґР° РІРѕР·РІСЂР°С‰Р°РµС‚ indicators СЃРѕ СЃР»РµРґСѓСЋС‰РёРјРё РєР»СЋС‡Р°РјРё:
  {price, ema20, ema50, rsi, macd_hist, atr, atr_pct}
- РґРѕР±Р°РІР»СЏРµС‚ market.condition Рё rule_score в€€ [0,1].
"""
from __future__ import annotations

from typing import Dict, Any, Optional
import math
import time

import pandas as pd

from crypto_ai_bot.core.indicators import unified as I


def _norm_symbol(sym: str) -> str:
    return sym.replace("-", "/").upper()


def _safe(df: pd.DataFrame, col: str, default: float = 0.0) -> float:
    try:
        return float(df[col].iloc[-1])
    except Exception:
        return default


def _compute_rule_score(last_price: float, ema20: float, ema50: float, rsi: float, macd_hist: float) -> float:
    # РџСЂРѕСЃС‚РµР№С€РёР№, РЅРѕ СЃС‚Р°Р±РёР»СЊРЅС‹Р№ СЃРєРѕСЂРёРЅРі [0..1]
    s_trend = 1.0 if (ema20 > ema50) else 0.0           # 0.0/1.0
    s_rsi = 1.0 - min(abs(rsi - 50.0) / 50.0, 1.0)      # Р±Р»РёР¶Рµ Рє 50 в†’ РІС‹С€Рµ
    s_macd = 1.0 if macd_hist > 0 else 0.0

    score = 0.5 * s_trend + 0.3 * s_rsi + 0.2 * s_macd
    return max(0.0, min(1.0, score))


def _fallback_features(last_price: float) -> Dict[str, Any]:
    ind = {
        "price": float(last_price),
        "ema20": float(last_price),
        "ema50": float(last_price),
        "rsi": 50.0,
        "macd_hist": 0.0,
        "atr": 0.0,
        "atr_pct": 0.0,
    }
    market = {"condition": "unknown"}
    rule_score = 0.5
    return {"indicators": ind, "market": market, "rule_score": rule_score}


def aggregate_features(cfg, exchange, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    sym = _norm_symbol(symbol or cfg.SYMBOL)
    tf = timeframe or cfg.TIMEFRAME
    lim = int(limit or max(cfg.AGGREGATOR_LIMIT, cfg.OHLCV_LIMIT))

    # 1) РџС‹С‚Р°РµРјСЃСЏ РїРѕР»СѓС‡РёС‚СЊ OHLCV СЃ СЂРµС‚СЂР°СЏРјРё
    ohlcv = None
    last_err = None
    for _ in range(3):
        try:
            ohlcv = exchange.fetch_ohlcv(sym, tf, lim)  # РѕР¶РёРґР°РµРј СЃРїРёСЃРѕРє [ts, o, h, l, c, v]
            if ohlcv and len(ohlcv) >= 5:
                break
        except Exception as e:
            last_err = e
        time.sleep(0.2)

    if not ohlcv:
        # 2) Fallback: Р±РµСЂС‘Рј last РёР· С‚РёРєРµСЂР°
        try:
            t = exchange.fetch_ticker(sym)
            last = float(t.get("last") or t.get("close") or 0.0)
        except Exception:
            last = 0.0
        return _fallback_features(last)

    # 3) РЎС‚СЂРѕРёРј DataFrame
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"]).astype(float)

    # 4) РРЅРґРёРєР°С‚РѕСЂС‹ (С‡РµСЂРµР· unified)
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    ema20_s = I.ema(close, 20)
    ema50_s = I.ema(close, 50)
    rsi_s   = I.rsi(close, cfg.ATR_PERIOD if cfg.ATR_PERIOD else 14)  # РїСѓСЃС‚СЊ РїРµСЂРёРѕРґ RSI в‰€ ATR_PERIOD РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ
    _, _, macd_hist_s = I.macd(close, 12, 26, 9)
    atr_s  = I.atr(high, low, close, cfg.ATR_PERIOD)
    atrp_s = I.atr_pct(high, low, close, cfg.ATR_PERIOD)

    last_price = float(close.iloc[-1])
    ema20 = float(ema20_s.iloc[-1])
    ema50 = float(ema50_s.iloc[-1])
    rsi = float(rsi_s.iloc[-1])
    macd_hist = float(macd_hist_s.iloc[-1])
    atr = float(atr_s.iloc[-1])
    atr_pct = float(atrp_s.iloc[-1])

    indicators = {
        "price": last_price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "atr": atr,
        "atr_pct": atr_pct,
    }

    market = {
        "condition": "bullish" if ema20 > ema50 else "bearish"
    }
    rule_score = _compute_rule_score(last_price, ema20, ema50, rsi, macd_hist)

    return {"indicators": indicators, "market": market, "rule_score": rule_score}






