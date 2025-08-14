
# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from typing import Any, Dict, Optional

import pandas as pd
import numpy as np

from crypto_ai_bot.analysis.technical_indicators import calculate_all_indicators

def _to_df(ohlcv: list) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","volume"]) if ohlcv else pd.DataFrame(columns=["time","open","high","low","close","volume"])  # noqa: E501
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)
        df = df.astype({"open":"float64","high":"float64","low":"float64","close":"float64","volume":"float64"})
    return df

def _market_condition(ind: Dict[str, float]) -> str:
    ema20 = ind.get("ema20") or 0.0
    ema50 = ind.get("ema50") or 0.0
    if ema20 > ema50: return "bullish"
    if ema20 < ema50: return "bearish"
    return "neutral"

def _base_rule_score(ind: Dict[str, float]) -> float:
    s = 0.5
    # тренд
    if (ind.get("ema20") or 0) > (ind.get("ema50") or 0): s += 0.2
    if (ind.get("ema20") or 0) < (ind.get("ema50") or 0): s -= 0.2
    # RSI
    rsi = ind.get("rsi")
    if rsi is not None:
        if 45 <= rsi <= 65: s += 0.05
        if rsi >= 80: s -= 0.15
        if rsi <= 20: s += 0.10
    # MACD hist
    macd = ind.get("macd_hist") or 0.0
    s += 0.05 if macd > 0 else -0.05
    return max(0.0, min(1.0, s))

def _apply_context_penalties(s: float, cfg) -> float:
    if int(getattr(cfg, "USE_CONTEXT_PENALTIES", 0)) != 1:
        return s
    # Заглушки: при отсутствии реальных источников контекста штрафы нулевые.
    # Но параметры cfg сохраняем для будущего расширения.
    s = s  # no-op
    s = max(getattr(cfg, "CTX_SCORE_CLAMP_MIN", 0.0), min(getattr(cfg, "CTX_SCORE_CLAMP_MAX", 1.0), s))
    return s

def aggregate_features(cfg, exchange: Any, symbol: str, limit: int = 200, timeframe: Optional[str] = None) -> Dict[str, Any]:
    try:
        tf = timeframe or getattr(cfg, "TIMEFRAME", "15m")
        raw = exchange.get_ohlcv(symbol, tf, limit=limit) if hasattr(exchange, "get_ohlcv") else []
        df = _to_df(raw)
        if df.empty:
            return {"error": "no_ohlcv"}

        feats = calculate_all_indicators(df)
        last = feats.iloc[-1]

        ind = {
            "rsi": float(last.get("rsi", np.nan)),
            "macd_hist": float(last.get("macd_hist", np.nan)),
            "ema9": float(last.get("ema9", np.nan)),
            "ema21": float(last.get("ema21", np.nan)),
            "ema20": float(last.get("ema20", np.nan)),
            "ema50": float(last.get("ema50", np.nan)),
            "atr": float(last.get("atr", np.nan)),
            "price": float(last.get("close", np.nan)),
            "volume_ratio": float(last.get("volume_ratio", 0.0)),
        }
        atr = ind.get("atr") or 0.0
        price = ind.get("price") or 0.0
        ind["atr_pct"] = float((atr / price) * 100.0) if price > 0 else 0.0

        base_rule = _base_rule_score(ind)
        rule_pen = _apply_context_penalties(base_rule, cfg)
        ai_score = float(getattr(cfg, "AI_FAILOVER_SCORE", 0.55))

        out = {
            "symbol": symbol,
            "timeframe": tf,
            "indicators": ind,
            "rule_score": base_rule,
            "rule_score_penalized": rule_pen,
            "ai_score": ai_score,
            "scores": {"rule": base_rule, "rule_penalized": rule_pen, "ai": ai_score},
            "market": {"condition": _market_condition(ind), "atr_pct": ind["atr_pct"]},
            "context": {"use_penalties": int(getattr(cfg, "USE_CONTEXT_PENALTIES", 0))},
        }
        return out
    except Exception as e:
        return {"error": str(e)}
