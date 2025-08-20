# src/crypto_ai_bot/core/signals/_fusion.py
"""
Fusion of indicator signals into a single trading decision.

- build(symbol, cfg, positions_repo=None, external=None, **_ignored) -> dict features
- decide(cfg, features) -> dict {action, score, explain}

Accepts extra kwargs (e.g., broker=...) for backward-compatibility with callers.
No external deps (numpy/pandas) to keep it lightweight.
"""

from __future__ import annotations
from typing import Any, Dict, List, Tuple

# Пороговые значения можно переопределять через Settings (cfg)
DEFAULTS = {
    "RSI_LEN": 14,
    "RSI_BUY": 35,       # ниже — перепроданность
    "RSI_SELL": 65,      # выше — перекупленность
    "MA_FAST": 20,
    "MA_SLOW": 50,
    "ATR_LEN": 14,
    "BUY_TH":  0.6,      # финальный скор > BUY_TH -> buy
    "SELL_TH": 0.6,      # финальный скор > SELL_TH -> sell
}

def _get(cfg: Any, name: str, default: Any) -> Any:
    if cfg is None:
        return default
    return getattr(cfg, name, getattr(cfg, name.lower(), default))

# ------------ small helpers (no external deps) ------------

def _sma(series: List[float], length: int) -> float | None:
    if not series or len(series) < length:
        return None
    return sum(series[-length:]) / float(length)

def _rsi(closes: List[float], length: int) -> float | None:
    if not closes or len(closes) <= length:
        return None
    gains = 0.0
    losses = 0.0
    # классическая Welles Wilder: используем простую оценку на последнем «окне»
    for i in range(-length, -1):
        diff = closes[i+1] - closes[i]
        if diff >= 0:
            gains += diff
        else:
            losses += -diff
    if gains == 0 and losses == 0:
        return 50.0
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))

def _atr(ohlcv: List[Tuple[int, float, float, float, float, float]], length: int) -> float | None:
    # ohlcv: [(ts, open, high, low, close, vol), ...]
    if not ohlcv or len(ohlcv) < length + 1:
        return None
    trs: List[float] = []
    for i in range(-length, 0):
        _, _o, h, l, _c, _v = ohlcv[i]
        _, _po, _ph, _pl, pc, _pv = ohlcv[i-1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / float(length) if trs else None

def _last_price(ohlcv: List[Tuple[int, float, float, float, float, float]] | None) -> float | None:
    if ohlcv and len(ohlcv) > 0:
        return float(ohlcv[-1][4])
    return None

# ----------------- public API -----------------

def build(
    symbol: str,
    *,
    cfg: Any,
    positions_repo: Any | None = None,
    external: Dict[str, Any] | None = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """
    Build features for `symbol`.
    external may contain:
      - "ohlcv": list of tuples (ts, open, high, low, close, vol)
    """
    rsi_len   = int(_get(cfg, "RSI_LEN",   DEFAULTS["RSI_LEN"]))
    ma_fast_n = int(_get(cfg, "MA_FAST",   DEFAULTS["MA_FAST"]))
    ma_slow_n = int(_get(cfg, "MA_SLOW",   DEFAULTS["MA_SLOW"]))
    atr_len   = int(_get(cfg, "ATR_LEN",   DEFAULTS["ATR_LEN"]))

    ohlcv = None
    if external and isinstance(external.get("ohlcv"), list):
        ohlcv = external["ohlcv"]

    closes: List[float] = [float(x[4]) for x in ohlcv] if ohlcv else []
    feat: Dict[str, Any] = {}

    last = _last_price(ohlcv)
    feat["last_price"] = last

    rsi = _rsi(closes, rsi_len) if closes else None
    feat["rsi"] = rsi

    ma_fast = _sma(closes, ma_fast_n) if closes else None
    ma_slow = _sma(closes, ma_slow_n) if closes else None
    feat["ma_fast"] = ma_fast
    feat["ma_slow"] = ma_slow

    atr = _atr(ohlcv, atr_len) if ohlcv else None
    feat["atr"] = atr

    # позиция (опционально)
    pos_qty = None
    if positions_repo is not None and hasattr(positions_repo, "get_position"):
        try:
            pos = positions_repo.get_position(symbol)
            pos_qty = (pos or {}).get("qty")
        except Exception:
            pos_qty = None
    feat["pos_qty"] = pos_qty

    return feat

def decide(cfg: Any, feat: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combine individual signals into a single decision.
    Returns:
      { "action": "buy"|"sell"|"hold", "score": float, "explain": {...} }
    """
    rsi_buy  = float(_get(cfg, "RSI_BUY",  DEFAULTS["RSI_BUY"]))
    rsi_sell = float(_get(cfg, "RSI_SELL", DEFAULTS["RSI_SELL"]))
    buy_th   = float(_get(cfg, "BUY_TH",   DEFAULTS["BUY_TH"]))
    sell_th  = float(_get(cfg, "SELL_TH",  DEFAULTS["SELL_TH"]))

    rsi  = feat.get("rsi")
    ma_f = feat.get("ma_fast")
    ma_s = feat.get("ma_slow")

    # нормируем частные скора 0..1
    s_buy, s_sell = 0.0, 0.0
    expl: Dict[str, Any] = {}

    # RSI компонент
    if isinstance(rsi, (int, float)):
        rsi_buy_sig  = max(0.0, min(1.0, (rsi_buy - rsi) / max(1.0, rsi_buy)))   # чем ниже RSI — тем ближе к 1
        rsi_sell_sig = max(0.0, min(1.0, (rsi - rsi_sell) / max(1.0, 100 - rsi_sell)))
        expl["rsi"] = {"value": rsi, "buy_sig": rsi_buy_sig, "sell_sig": rsi_sell_sig}
        s_buy  += 0.5 * rsi_buy_sig
        s_sell += 0.5 * rsi_sell_sig
    else:
        expl["rsi"] = {"value": None}

    # MA кроссовер
    ma_buy_sig = 0.0
    ma_sell_sig = 0.0
    if isinstance(ma_f, (int, float)) and isinstance(ma_s, (int, float)):
        if ma_f > ma_s:
            ma_buy_sig = min(1.0, (ma_f - ma_s) / max(1e-9, abs(ma_s)))
        elif ma_f < ma_s:
            ma_sell_sig = min(1.0, (ma_s - ma_f) / max(1e-9, abs(ma_s)))
    expl["ma"] = {"ma_fast": ma_f, "ma_slow": ma_s, "buy_sig": ma_buy_sig, "sell_sig": ma_sell_sig}
    s_buy  += 0.5 * ma_buy_sig
    s_sell += 0.5 * ma_sell_sig

    # итог
    action = "hold"
    score  = 0.0
    if s_buy >= buy_th and s_buy >= s_sell:
        action = "buy"
        score = s_buy
    elif s_sell >= sell_th and s_sell > s_buy:
        action = "sell"
        score = s_sell

    return {"action": action, "score": float(score), "explain": expl}
