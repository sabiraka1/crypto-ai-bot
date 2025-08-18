# src/crypto_ai_bot/core/signals/context_blend.py
from __future__ import annotations

from typing import Dict, Optional


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _to_01(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    # допускаем проценты (0..100) и доли (0..1)
    if v > 1.0:
        v = v / 100.0
    return _clamp(v, 0.0, 1.0)


def _to_pm1_from_01(z: Optional[float]) -> float:
    """0..1 -> -1..+1"""
    if z is None:
        return 0.0
    return _clamp(2.0 * z - 1.0, -1.0, 1.0)


def compute_context_score(
    ctx: Dict[str, Optional[float]],
    *,
    w_btc_dom: float = 0.0,
    w_fng: float = 0.0,
    w_dxy: float = 0.0,
) -> float:
    """
    Считает контекстный скор в диапазоне [-1..+1].
    - BTC dominance: выше → чуть более бычий (по умолчанию 0 вес)
    - Fear&Greed (0..100): выше (жадность) → бычий
    - DXY (~100): выше → чаще медвежий для рисковых активов (инвертируем)
    """
    # btc.dominance
    dom01 = _to_01(ctx.get("btc_dominance"))
    s_dom = _to_pm1_from_01(dom01)  # -1..+1

    # fear&greed
    fng01 = _to_01(ctx.get("fear_greed"))
    s_fng = _to_pm1_from_01(fng01)  # -1..+1

    # dxy: центрируем возле 100, диапазон +/-20 → нормируем в [-1..+1] и инвертируем
    dxy_val = ctx.get("dxy")
    if dxy_val is None:
        s_dxy = 0.0
    else:
        try:
            dxy = float(dxy_val)
        except Exception:
            dxy = 100.0
        s_dxy = -_clamp((dxy - 100.0) / 20.0, -1.0, 1.0)

    w_dom = max(0.0, float(w_btc_dom))
    w_f = max(0.0, float(w_fng))
    w_dx = max(0.0, float(w_dxy))
    W = w_dom + w_f + w_dx
    if W <= 0:
        return 0.0

    score = (w_dom * s_dom + w_f * s_fng + w_dx * s_dxy) / W
    return _clamp(score, -1.0, 1.0)


def blend_scores(baseline_01: float, ctx_pm1: float, *, alpha: float) -> float:
    """
    Смешиваем базовый score [0..1] с контекстом [-1..+1].
    Переводим контекст к [0..1] как 0.5*(ctx+1) и линейно смешиваем.
    alpha=0 => без изменений. alpha=1 => полностью контекст.
    """
    b = _clamp(float(baseline_01), 0.0, 1.0)
    a = _clamp(float(alpha), 0.0, 1.0)
    c01 = _clamp(0.5 * (float(ctx_pm1) + 1.0), 0.0, 1.0)
    out = (1.0 - a) * b + a * c01
    return _clamp(out, 0.0, 1.0)
