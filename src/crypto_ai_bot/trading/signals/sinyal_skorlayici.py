
# -*- coding: utf-8 -*-
from __future__ import annotations

# crypto_ai_bot/sinyal_skorlayici.py
# ----------------------------------
# РџСЂРѕСЃС‚Р°СЏ, РЅРѕ РєРѕСЂСЂРµРєС‚РЅР°СЏ С‚СЂРµРЅРёСЂРѕРІРєР° РјРѕРґРµР»Рё СЃ TimeSeriesSplit (walk-forward).
# - Р—Р°РіСЂСѓР¶Р°РµС‚ OHLCV С‡РµСЂРµР· ccxt (СЂРµР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ) РїРѕ SYMBOL/TIMEFRAME/LOOKBACK
# - РЎС‚СЂРѕРёС‚ РїСЂРёР·РЅР°РєРё РёР· crypto_ai_bot.core.indicators.unified
# - Р¦РµР»СЊ: Р±СѓРґРµС‚ Р»Рё РґРѕС…РѕРґРЅРѕСЃС‚СЊ Р·Р° РіРѕСЂРёР·РѕРЅС‚РѕРј H > T% РґРѕ СѓС…РѕРґР° РЅРёР¶Рµ -S% (СѓРїСЂРѕС‰С‘РЅРЅР°СЏ РјРµС‚РєР°)
# - РњРѕРґРµР»СЊ: LogisticRegression (scikit-learn) + СЃРѕС…СЂР°РЅРµРЅРёРµ РІ models/
# - Р’РѕР·РІСЂР°С‰Р°РµС‚ РєРѕСЂРѕС‚РєРёР№ С‚РµРєСЃС‚РѕРІС‹Р№ РѕС‚С‡С‘С‚

import os
from typing import Dict, Any
import numpy as np
import pandas as pd

try:
    import ccxt
except Exception:
    ccxt = None

from sklearn.model_selection import TimeSeriesSplit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, precision_recall_fscore_support
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib

from crypto_ai_bot.core.indicators.unified import calculate_all_indicators


def _exchange():
    if not ccxt:
        raise RuntimeError("ccxt not available")
    key = os.getenv("GATE_API_KEY") or os.getenv("API_KEY")
    secret = os.getenv("GATE_API_SECRET") or os.getenv("API_SECRET")
    return ccxt.gateio({
        "apiKey": key,
        "secret": secret,
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {"defaultType": "spot"}
    })


def _load_ohlcv(symbol: str, timeframe: str, limit: int = 1500) -> pd.DataFrame:
    ex = _exchange()
    data = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(data, columns=["time","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    return df


def _make_labels(df: pd.DataFrame, horizon: int = 8, up_pct: float = 0.6, down_pct: float = 0.6) -> pd.Series:
    # РџСЂРѕСЃС‚Р°СЏ РіРѕСЂРёР·РѕРЅС‚-РјРµС‚РєР°: 1, РµСЃР»Рё РІ С‚РµС‡РµРЅРёРµ horizon Р±Р°СЂРѕРІ РІРїРµСЂС‘Рґ С†РµРЅР° РїРѕРґРЅРёРјРµС‚СЃСЏ РЅР° up_pct% СЂР°РЅСЊС€Рµ,
    # С‡РµРј РѕРїСѓСЃС‚РёС‚СЃСЏ РЅР° down_pct%; РёРЅР°С‡Рµ 0.
    c = df["close"].values
    up_thr = 1.0 + up_pct/100.0
    dn_thr = 1.0 - down_pct/100.0
    y = np.zeros(len(c), dtype=int)
    for i in range(len(c)-horizon):
        base = c[i]
        up_hit = dn_hit = None
        for j in range(1, horizon+1):
            r = c[i+j] / base
            if up_hit is None and r >= up_thr: up_hit = j
            if dn_hit is None and r <= dn_thr: dn_hit = j
            if up_hit is not None and dn_hit is not None: break
        y[i] = 1 if (up_hit is not None and (dn_hit is None or up_hit < dn_hit)) else 0
    return pd.Series(y, index=df.index)


def train_model() -> str:
    symbol = os.getenv("SYMBOL", "BTC/USDT")
    timeframe = os.getenv("TIMEFRAME", "15m")
    lookback = int(os.getenv("TRAIN_LOOKBACK", "1200"))
    horizon = int(os.getenv("TRAIN_HORIZON", "8"))
    up_pct = float(os.getenv("TRAIN_UP_PCT", "0.6"))
    down_pct = float(os.getenv("TRAIN_DOWN_PCT", "0.6"))

    df = _load_ohlcv(symbol, timeframe, limit=lookback)
    feats = calculate_all_indicators(df)
    feats = feats.dropna().copy()

    # Р¦РµР»СЊ
    y = _make_labels(feats, horizon=horizon, up_pct=up_pct, down_pct=down_pct)
    y = y.reindex(feats.index).fillna(0).astype(int)

    # РњР°С‚СЂРёС†Р° РїСЂРёР·РЅР°РєРѕРІ
    X = feats[["rsi","macd_hist","ema9","ema21","ema20","ema50","atr","volume_ratio"]].astype(float).values

    # Walk-forward
    tscv = TimeSeriesSplit(n_splits=5)
    aucs = []; prs = []; recs = []; f1s = []

    model = Pipeline([
        ("scaler", StandardScaler(with_mean=False)),
        ("clf", LogisticRegression(max_iter=200))
    ])

    for train_idx, test_idx in tscv.split(X):
        Xtr, Xte = X[train_idx], X[test_idx]
        ytr, yte = y.iloc[train_idx], y.iloc[test_idx]
        model.fit(Xtr, ytr)
        proba = model.predict_proba(Xte)[:,1]
        pred = (proba >= 0.5).astype(int)
        aucs.append(roc_auc_score(yte, proba))
        pr, rc, f1, _ = precision_recall_fscore_support(yte, pred, average="binary", zero_division=0)
        prs.append(pr); recs.append(rc); f1s.append(f1)

    # РћР±СѓС‡Р°РµРј РЅР° РІСЃС‘Рј Рё СЃРѕС…СЂР°РЅСЏРµРј
    model.fit(X, y.values)
    model_dir = os.getenv("MODEL_DIR", "models")
    os.makedirs(model_dir, exist_ok=True)
    out_path = os.path.join(model_dir, "signal_model.joblib")
    joblib.dump(model, out_path)

    msg = (
        f"MODEL trained for {symbol} {timeframe}\n"
        f"AUC(meanВ±std): {np.mean(aucs):.3f}В±{np.std(aucs):.3f}\n"
        f"P/R/F1: {np.mean(prs):.2f}/{np.mean(recs):.2f}/{np.mean(f1s):.2f}\n"
        f"Saved: {out_path}"
    )
    return msg











