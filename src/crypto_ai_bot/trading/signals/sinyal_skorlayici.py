
# -*- coding: utf-8 -*-
from __future__ import annotations

# crypto_ai_bot/sinyal_skorlayici.py
# ----------------------------------
# Простая, но корректная тренировка модели с TimeSeriesSplit (walk-forward).
# - Загружает OHLCV через ccxt (реальные данные) по SYMBOL/TIMEFRAME/LOOKBACK
# - Строит признаки из analysis.technical_indicators
# - Цель: будет ли доходность за горизонтом H > T% до ухода ниже -S% (упрощённая метка)
# - Модель: LogisticRegression (scikit-learn) + сохранение в models/
# - Возвращает короткий текстовый отчёт

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

from crypto_ai_bot.analysis.technical_indicators import calculate_all_indicators


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
    # Простая горизонт-метка: 1, если в течение horizon баров вперёд цена поднимется на up_pct% раньше,
    # чем опустится на down_pct%; иначе 0.
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

    # Цель
    y = _make_labels(feats, horizon=horizon, up_pct=up_pct, down_pct=down_pct)
    y = y.reindex(feats.index).fillna(0).astype(int)

    # Матрица признаков
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

    # Обучаем на всём и сохраняем
    model.fit(X, y.values)
    model_dir = os.getenv("MODEL_DIR", "models")
    os.makedirs(model_dir, exist_ok=True)
    out_path = os.path.join(model_dir, "signal_model.joblib")
    joblib.dump(model, out_path)

    msg = (
        f"MODEL trained for {symbol} {timeframe}\n"
        f"AUC(mean±std): {np.mean(aucs):.3f}±{np.std(aucs):.3f}\n"
        f"P/R/F1: {np.mean(prs):.2f}/{np.mean(recs):.2f}/{np.mean(f1s):.2f}\n"
        f"Saved: {out_path}"
    )
    return msg
